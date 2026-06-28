import frappe
import datetime
import xml.etree.ElementTree as ET
import subprocess
from zeep import Client
import os


def _resolve_private_file_path(file_url):
    """Resolve an Attach field value to an absolute path inside the current site."""
    if not file_url:
        return None

    normalized = str(file_url).strip()
    if not normalized:
        return None

    # Attach values are usually like /private/files/<filename>
    if normalized.startswith("/"):
        normalized = normalized.lstrip("/")

    return frappe.get_site_path(normalized)

def check_token_validity():
    """Check if the existing token is still valid"""
    try:
        afip_settings = frappe.get_doc("AFIP Setting")
        if not afip_settings.token or not afip_settings.sign:
            return False
        
        # Get the expiration time from the token
        token_bytes = afip_settings.token.encode('utf-8')
        token_xml = ET.fromstring(token_bytes)
        expiration_time = token_xml.find('.//exp_time')
        
        if expiration_time is not None:
            expiration_time = datetime.datetime.fromtimestamp(int(expiration_time.text))
            current_time = datetime.datetime.now()
            
            # Return True if token is still valid (considering a small buffer)
            return current_time < (expiration_time - datetime.timedelta(minutes=10))
            
        return False
    except Exception:
        return False


def get_afip_token():
    try:
        afip_settings = frappe.get_doc("AFIP Setting")

        # First check if we have a valid token
        if check_token_validity():
            frappe.msgprint("Using existing valid AFIP token")
            return {
                "success": True,
                "token": afip_settings.token,
                "sign": afip_settings.sign
            }
        
        # If no valid token exists, proceed with generating a new one
        # Set the service ID (replace with your actual service ID)
        servicio_id = "wsfe"

        # Set certificate and private key paths from AFIP Setting attached files
        certificado = _resolve_private_file_path(afip_settings.certificate)
        clave_privada = _resolve_private_file_path(afip_settings.private_key)

        if not certificado:
            frappe.throw("AFIP Setting requires a Certificate file.")
        if not clave_privada:
            frappe.throw("AFIP Setting requires a Private key file.")
        
        # Verify files exist
        if not os.path.exists(certificado):
            frappe.throw(f"Certificate file not found at {certificado}")
        if not os.path.exists(clave_privada):
            frappe.throw(f"Private key file not found at {clave_privada}")
        
        # Set WSDL URL according to environment
        if afip_settings.use_sandbox_environment:
            wsaa_wsdl = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
        else:
            wsaa_wsdl = "https://wsaa.afip.gov.ar/ws/services/LoginCms?WSDL"
        
        # Create XML access ticket
        dt_now = datetime.datetime.utcnow()
        
        # Create XML structure
        root = ET.Element("loginTicketRequest")
        header = ET.SubElement(root, "header")
        unique_id = ET.SubElement(header, "uniqueId")
        generation_time = ET.SubElement(header, "generationTime")
        expiration_time = ET.SubElement(header, "expirationTime")
        service = ET.SubElement(root, "service")
        
        # Set times using proper UTC format
        generation_time.text = (dt_now).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        expiration_time.text = (dt_now + datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        unique_id.text = dt_now.strftime("%y%m%d%H%M")
        service.text = servicio_id
        
        seq_nr = dt_now.strftime("%Y%m%d%H%M%S")
        out_xml = f"{seq_nr}-LoginTicketRequest.xml"
        out_cms_der = f"{seq_nr}-LoginTicketRequest.xml.cms-DER"
        out_cms_der_b64 = f"{seq_nr}-LoginTicketRequest.xml.cms-DER-b64"
        
        try:
            # Write XML to file
            xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
            with open(out_xml, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            
            # Sign CMS
            subprocess.run([
                'openssl', 'smime', '-sign',
                '-in', out_xml,
                '-signer', certificado,
                '-inkey', clave_privada,
                '-nodetach',
                '-outform', 'der',
                '-out', out_cms_der
            ], check=True)
            
            # Encode in BASE64
            subprocess.run([
                'openssl', 'base64',
                '-in', out_cms_der,
                '-e',
                '-out', out_cms_der_b64
            ], check=True)
            
            with open(out_cms_der_b64, 'r') as f:
                cms = f.read()
            
            # Call WSAA
            client = Client(wsaa_wsdl)
            wsaa_response = client.service.loginCms(cms)
            
            # Parse response and update settings
            response_root = ET.fromstring(wsaa_response)
            token = response_root.find('.//credentials/token').text
            sign = response_root.find('.//credentials/sign').text
            
            afip_settings.token = token
            afip_settings.sign = sign
            afip_settings.save()
            
            frappe.db.commit()
            
            frappe.msgprint("AFIP token and sign updated successfully")
            
            return {
                "success": True,
                "token": token,
                "sign": sign
            }
            
        except Exception as e:
            frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
            frappe.throw(f"Error generating AFIP token: {str(e)}")
            
        finally:
            # Cleanup temporary files
            for file in [out_xml, out_cms_der, out_cms_der_b64]:
                if os.path.exists(file):
                    os.remove(file)
                    
    except Exception as e:
        frappe.log_error(f"AFIP Token Generation Error: {str(e)}")
        frappe.throw(f"Error in AFIP token generation: {str(e)}")