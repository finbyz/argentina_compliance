import frappe
import datetime
import xml.etree.ElementTree as ET
import subprocess
from zeep import Client
import os
import re


def _afip_token_error_guidance(raw_error):
    """Map raw AFIP/WSAA errors to actionable user-facing guidance."""
    msg = (str(raw_error) or "").strip()
    normalized = msg.lower()

    if "computador no autorizado a acceder al servicio" in normalized:
        return (
            "AFIP rejected the certificate for service wsfe in this environment. "
            "Please verify in ARCA/AFIP that this certificate is associated to WSFE "
            "for the same CUIT and environment (homologation vs production), then try again."
        )

    if "ya posee un ta valido" in normalized or "ya posee un ta válido" in normalized:
        return (
            "AFIP reports there is already an active TA (token) for this certificate/service. "
            "Use the current token/sign (without forcing a new one) or wait for expiration before requesting a new TA."
        )

    if "generationtime posee formato o dato inválido" in normalized:
        return (
            "AFIP rejected the Login Ticket timestamp. "
            "Please verify server clock synchronization (NTP/UTC) and retry."
        )

    if "certificate" in normalized and "not found" in normalized:
        return "Certificate file is missing. Re-upload the AFIP certificate in AFIP Setting and retry."

    if "private key" in normalized and "not found" in normalized:
        return "Private key file is missing. Re-upload the AFIP private key in AFIP Setting and retry."

    if "unable to load" in normalized and "private key" in normalized:
        return (
            "Private key could not be read by OpenSSL. "
            "Confirm the key format is valid PEM and that it matches the uploaded certificate."
        )

    if "certificate verify failed" in normalized or "ssl" in normalized:
        return (
            "TLS/SSL connection to AFIP failed. "
            "Please check network/firewall/proxy rules and retry."
        )

    return (
        "AFIP token generation failed. "
        "Please review certificate/private key, AFIP service authorization, and environment settings."
    )


def _extract_afip_error_details(raw_error):
    """Extract error details from AFIP/ARCA SOAP faults when available."""
    message = (str(raw_error) or "").strip()
    fault_code = None
    error_code = None

    # Zeep SOAP Fault usually exposes .code and .detail
    if getattr(raw_error, "code", None):
        fault_code = str(raw_error.code)

    detail = getattr(raw_error, "detail", None)
    detail_text = ""
    if detail is not None:
        try:
            detail_text = str(detail)
        except Exception:
            detail_text = ""

    combined = "\n".join([x for x in [message, detail_text] if x])

    # Try common patterns to capture explicit error codes in messages/details.
    patterns = [
        r"\b(?:code|codigo|código)\s*[:=]\s*([A-Za-z0-9\-_]+)",
        r"\berr(?:or)?\s*[:=]\s*([A-Za-z0-9\-_]+)",
        r"\bafip\s*[:#-]?\s*([A-Za-z0-9\-_]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, combined, flags=re.IGNORECASE)
        if match:
            error_code = match.group(1)
            break

    return {
        "error_code": error_code,
        "fault_code": fault_code,
        "message": message,
        "detail": detail_text,
    }


def _build_user_error_message(raw_error):
    guidance = _afip_token_error_guidance(raw_error)
    details = _extract_afip_error_details(raw_error)

    afip_code = details.get("error_code") or "N/A"
    afip_fault = details.get("fault_code") or "N/A"
    afip_message = details.get("message") or "N/A"

    return (
        f"{guidance}\n\n"
        "AFIP/ARCA response details:\n"
        f"- Error code: {afip_code}\n"
        f"- Fault code: {afip_fault}\n"
        f"- Message: {afip_message}"
    )


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


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
            expiration_time = datetime.datetime.utcfromtimestamp(int(expiration_time.text))
            current_time = datetime.datetime.utcnow()
            
            # Return True if token is still valid (considering a small buffer)
            return current_time < (expiration_time - datetime.timedelta(minutes=10))
            
        return False
    except Exception:
        return False


@frappe.whitelist()
def get_afip_token(force_new=0):
    try:
        afip_settings = frappe.get_doc("AFIP Setting")

        # First check if we have a valid token
        if not _as_bool(force_new) and check_token_validity():
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
        # Use a skew-tolerant window to avoid WSAA rejecting generationTime when
        # there is small clock drift between servers.
        dt_now = datetime.datetime.utcnow()
        generation_dt = dt_now - datetime.timedelta(minutes=10)
        expiration_dt = dt_now + datetime.timedelta(hours=12)
        
        # Create XML structure
        root = ET.Element("loginTicketRequest")
        header = ET.SubElement(root, "header")
        unique_id = ET.SubElement(header, "uniqueId")
        generation_time = ET.SubElement(header, "generationTime")
        expiration_time = ET.SubElement(header, "expirationTime")
        service = ET.SubElement(root, "service")
        
        # Use second precision and UTC suffix for WSAA-compatible timestamps.
        generation_time.text = generation_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        expiration_time.text = expiration_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        unique_id.text = str(int(dt_now.timestamp()))
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
            user_message = _build_user_error_message(e)
            details = _extract_afip_error_details(e)
            frappe.log_error(
                message=(
                    f"AFIP Token Generation Error: {str(e)}\n"
                    f"User message: {user_message}\n"
                    f"AFIP error code: {details.get('error_code') or 'N/A'}\n"
                    f"AFIP fault code: {details.get('fault_code') or 'N/A'}\n"
                    f"AFIP detail: {details.get('detail') or 'N/A'}\n"
                    f"Certificate path: {certificado}\n"
                    f"Private key path: {clave_privada}\n"
                    f"WSAA WSDL: {wsaa_wsdl}\n"
                    f"Sandbox: {int(bool(afip_settings.use_sandbox_environment))}\n"
                ),
                title="AFIP Token Generation Error"
            )
            frappe.throw(user_message)
            
        finally:
            # Cleanup temporary files
            for file in [out_xml, out_cms_der, out_cms_der_b64]:
                if os.path.exists(file):
                    os.remove(file)
                    
    except Exception as e:
        if isinstance(e, frappe.ValidationError):
            raise

        user_message = _build_user_error_message(e)
        details = _extract_afip_error_details(e)
        frappe.log_error(
            message=(
                f"AFIP Token Generation Error: {str(e)}\n"
                f"User message: {user_message}\n"
                f"AFIP error code: {details.get('error_code') or 'N/A'}\n"
                f"AFIP fault code: {details.get('fault_code') or 'N/A'}\n"
                f"AFIP detail: {details.get('detail') or 'N/A'}"
            ),
            title="AFIP Token Generation Error"
        )
        frappe.throw(user_message)