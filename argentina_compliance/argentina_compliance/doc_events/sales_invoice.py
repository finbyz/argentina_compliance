import frappe
import zeep
from datetime import datetime
import base64
import json
from zeep.exceptions import Fault
import traceback
from argentina_compliance.argentina_compliance.doctype.afip_setting.afip_setting import log_electronic_invoice_error

def _to_int_or_default(value, default=0):
    """Convert a value to int, accepting formatted numeric strings like CUIT."""
    if value is None:
        return default

    text = str(value).strip()
    if not text:
        return default

    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return default

    try:
        return int(digits)
    except Exception:
        return default


def get_pos_number(sales_invoice):
    """Resolve POS number from invoice fields in a v16-safe way."""
    custom_pos = _to_int_or_default(getattr(sales_invoice, "custom_point_of_sale", None), 0)
    if custom_pos > 0:
        return custom_pos

    pos_from_profile = _to_int_or_default(getattr(sales_invoice, "pos_profile", None), 0)
    if pos_from_profile > 0:
        return pos_from_profile

    return 1


def extract_invoice_number(invoice_name, invoice_type=None):
    """
    Extract the numeric sequence from invoice name
    Args:
        invoice_name (str): Full invoice name (e.g., 'ACC-SINV-2025-00035')
        invoice_type (int): AFIP invoice type
    Returns:
        int: Sequence number for AFIP
    """
    try:
        # Debug log
        # frappe.log_error(
        #     message=f"Extracting number from: {invoice_name} for type: {invoice_type}",
        #     title="Invoice Number Extraction Debug"
        # )
        
        # Split the invoice name and get the last part
        parts = invoice_name.split('-')
        if len(parts) < 2:
            frappe.throw(f"Invalid invoice name format: {invoice_name}")
        
        # Get the last numeric part and remove leading zeros
        numeric_part = parts[-1].lstrip('0')
        if not numeric_part:
            numeric_part = "0"  # Handle case where number is all zeros
            
        if not numeric_part.isdigit():
            frappe.throw(f"Could not extract numeric sequence from invoice name: {invoice_name}")
        
        return int(numeric_part)
        
    except Exception as e:
        frappe.throw(f"Error extracting invoice number: {str(e)}")

def get_invoice_type(sales_invoice):
    """
    Map ERPNext invoice types to AFIP types
    Args:
        sales_invoice: Sales Invoice document
    Returns:
        int: AFIP invoice type code
    """
    try:
        # # Debug log
        # frappe.log_error(
        #     message=f"Getting invoice type for invoice: {sales_invoice.name}",
        #     title="Invoice Type Debug"
        # )
        
        # Get customer VAT status
        vat_status = frappe.get_value(
            "Customer", 
            sales_invoice.customer, 
            "custom_vat_status"
        )
        
        # Debug log customer details
        # frappe.log_error(
        #     message=f"""
        #     Customer VAT details:
        #     - Customer: {sales_invoice.customer}
        #     - VAT Status: {vat_status}
        #     """,
        #     title="Customer VAT Status"
        # )
        
        mapping = {
            "Final Consumer": 6,
            "Exempt": 6,
            "Monotributo Manager": 11,
            "Registered Responsible": 1,
            "Uncategorized": 1
        }
        
        invoice_type = mapping.get(vat_status, 1)
        
        # Debug log result
        # frappe.log_error(
        #     message=f"Mapped invoice type: {invoice_type}",
        #     title="Invoice Type Result"
        # )
        
        return invoice_type
        
    except Exception as e:
        frappe.log_error(
            message=f"Error in get_invoice_type: {str(e)}",
            title="Invoice Type Error"
        )
        return 1  # Default to type 1 if error occurs

def get_customer_condition_id(sales_invoice):
    """
    Map ERPNext invoice types to AFIP types
    Args:
        sales_invoice: Sales Invoice document
    Returns:
        int: AFIP invoice type code
    """
    try:
        
        # Get customer VAT status
        vat_status = frappe.get_value(
            "Customer", 
            sales_invoice.customer, 
            "custom_vat_status"
        )
        

        # AFIP CondicionIVAReceptorId expects numeric IDs.
        mapping = {
            "Registered Responsible": 1,
            "Exempt": 4,
            "Final Consumer": 5,
            "Monotributo Manager": 6,
            "Uncategorized": 5,
        }

        return mapping.get(vat_status, 5)
        
    except Exception as e:
        frappe.log_error(
            message=f"Error in get_invoice_type: {str(e)}",
            title="Invoice Type Error"
        )
        return 1  # Default to type 1 if error occurs

def get_next_number(invoice_type, pos_number):
    """
    Get the next available number for a specific invoice type and POS
    Args:
        invoice_type (int): AFIP invoice type
        pos_number (int): Point of Sale number
    Returns:
        int: Next available number
    """
    try:
        # Get AFIP settings and client
        afip_details = frappe.get_doc("AFIP Setting")
        client = get_afip_client(afip_details)
        
        # Get authentication data
        auth = {
            'Token': afip_details.token.strip(),
            'Sign': afip_details.sign.strip(),
            'Cuit': int(afip_details.cuit)
        }
        
        # Get last authorized number from AFIP
        last_number = get_last_authorized_invoice(client, auth, pos_number, invoice_type)
        
        return last_number + 1
        
    except Exception as e:
        frappe.throw(f"Error getting next invoice number: {str(e)}")

def validate_invoice_sequence(sales_invoice):
    """
    Validate invoice sequence before submitting to AFIP
    Args:
        sales_invoice (object): Sales Invoice document
    """
    try:
        pos_number = get_pos_number(sales_invoice)
        invoice_type = get_invoice_type(sales_invoice)
        
        # Get the numeric sequence from invoice name
        current_number = extract_invoice_number(sales_invoice.name, invoice_type)
        
        # Get what should be the next number from AFIP
        expected_number = get_next_number(invoice_type, pos_number)
        
        if current_number != expected_number:
            frappe.throw(
                f"Invalid invoice sequence for type {invoice_type}. Expected {expected_number}, "
                f"got {current_number}. Please check the last authorized invoice in AFIP."
            )
            
    except Exception as e:
        frappe.throw(f"Error validating invoice sequence: {str(e)}")

def get_afip_client(afip_details):
    """
    Initialize and return AFIP SOAP client based on environment settings
    
    Args:
        afip_details: AFIP Setting document with configuration
        
    Returns:
        zeep.Client: Initialized SOAP client for AFIP web services
    """
    try:
        # Determine WSDL URL based on environment
        if afip_details.use_sandbox_environment:
            wsdl = 'https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL'
        else:
            wsdl = 'https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL'
            
        # Initialize ZEEP client
        client = zeep.Client(wsdl=wsdl)
        return client
        
    except Exception as e:
        frappe.throw(f"Error initializing AFIP client: {str(e)}")

def get_last_authorized_invoice(client, auth, pos_number, invoice_type):
    """
    Get the last authorized invoice number from AFIP
    """
    try:
        response = client.service.FECompUltimoAutorizado(auth, pos_number, invoice_type)
        if hasattr(response, 'Errors') and response.Errors:
            error_msg = format_afip_errors(response.Errors)
            frappe.throw(f"AFIP Error: {error_msg}")
        return response.CbteNro
    except Exception as e:
        frappe.throw(f"Error getting last authorized invoice: {str(e)}")

@frappe.whitelist()
def generate_invoice(salesInvoice):
    try:
        # Get AFIP settings
        afip_details = frappe.get_doc("AFIP Setting")
        if not all([afip_details.token, afip_details.sign, afip_details.cuit]):
            frappe.throw("Missing AFIP credentials. Please check AFIP Settings.")

        # Initialize WSFE client
        client = get_afip_client(afip_details)

        # Prepare authentication data
        auth = {
            'Token': afip_details.token.strip(),
            'Sign': afip_details.sign.strip(),
            'Cuit': int(afip_details.cuit)
        }

        # Get sales invoice details
        sales_invoice = frappe.get_doc("Sales Invoice", salesInvoice)
        customer = frappe.get_doc("Customer", sales_invoice.customer)
        
        # Get POS number and invoice type
        pos_number = get_pos_number(sales_invoice)
        invoice_type = get_invoice_type(sales_invoice)

        # Get the numeric sequence from invoice name
        current_number = extract_invoice_number(sales_invoice.name, invoice_type)

        # Get last authorized number from AFIP
        last_invoice = get_last_authorized_invoice(client, auth, pos_number, invoice_type)
        expected_number = last_invoice + 1

        # Validate invoice number sequence
        if current_number != expected_number:
            frappe.throw(
                f"Invalid invoice number sequence. Expected {expected_number}, got {current_number}. "
                "Please check the last authorized invoice in AFIP."
            )

        # Calculate VAT
        vat_tax = 0
        for tax in sales_invoice.taxes:
            if tax.rate > 0:
                vat_tax = tax.rate
                break

        # Get current date in AFIP format
        formatted_date = sales_invoice.posting_date.strftime('%Y%m%d')

        # Calculate amounts
        total_amount = float(sales_invoice.grand_total)
        net_amount = float(sales_invoice.net_total)
        vat_amount = float(sales_invoice.total_taxes_and_charges)

        # Prepare invoice data
        invoice = {
            'FeCabReq': {
                'CantReg': 1,
                'PtoVta': pos_number,
                'CbteTipo': invoice_type
            },
            'FeDetReq': {
                'FECAEDetRequest': [{
                    'Concepto': 1,
                    'DocTipo': get_doc_type(customer),
                    'DocNro': _to_int_or_default(customer.tax_id, 0),
                    'CbteDesde': current_number,
                    'CondicionIVAReceptorId': get_customer_condition_id(sales_invoice),
                    'CbteHasta': current_number,
                    'CbteFch': formatted_date,
                    'ImpTotal': round(total_amount, 2),
                    'ImpTotConc': 0.0,
                    'ImpNeto': round(net_amount, 2),
                    'ImpOpEx': 0.0,
                    'ImpIVA': round(vat_amount, 2),
                    'ImpTrib': 0.0,
                    'MonId': 'PES',
                    'MonCotiz': 1.0,
                    'Iva': {
                        'AlicIva': [{
                            'Id': get_vat_rate_id(vat_tax),
                            'BaseImp': round(net_amount, 2),
                            'Importe': round(vat_amount, 2)
                        }]
                    }
                }]
            }
        }

        try:
            # Add transport logging
            import logging.config
            logging.config.dictConfig({
                'version': 1,
                'formatters': {
                    'verbose': {
                        'format': '%(name)s: %(message)s'
                    }
                },
                'handlers': {
                    'console': {
                        'level': 'DEBUG',
                        'class': 'logging.StreamHandler',
                        'formatter': 'verbose',
                    },
                },
                'loggers': {
                    'zeep.transports': {
                        'level': 'DEBUG',
                        'propagate': True,
                        'handlers': ['console'],
                    },
                }
            })

            # # Pre-request validation
            # frappe.log_error(
            #     message=f"Pre-request validation:\nToken length: {len(auth['Token'])}\nSign length: {len(auth['Sign'])}\nCUIT: {auth['Cuit']}",
            #     title="AFIP Debug - Pre-request"
            # )
            
            response = client.service.FECAESolicitar(auth, invoice)
            
            # Log raw response for debugging
            frappe.log_error(
                message=f"AFIP Raw Response: {response}",
                title="AFIP Debug - Response"
            )
            
            # Check if response has Errors
            if hasattr(response, 'Errors') and response.Errors:
                error_msg = format_afip_errors(response.Errors)
                frappe.throw(f"AFIP Error Response: {error_msg}")

            # Check for FeDetResp structure correctly
            if (hasattr(response, 'FeDetResp') and 
                hasattr(response.FeDetResp, 'FECAEDetResponse') and 
                response.FeDetResp.FECAEDetResponse):
                
                det_resp = response.FeDetResp.FECAEDetResponse[0]
                
                # Log any observations
                if hasattr(det_resp, 'Observaciones') and det_resp.Observaciones:
                    obs_msg = "; ".join([
                        f"Warning {obs.Code}: {obs.Msg}" 
                        for obs in det_resp.Observaciones.Obs
                    ])
                    frappe.msgprint(f"AFIP Warnings: {obs_msg}", indicator='orange')

                # Check resultado and get CAE
                if det_resp.Resultado == 'A' and hasattr(det_resp, 'CAE'):
                    cae = det_resp.CAE
                    cae_vto = det_resp.CAEFchVto
                    
                    # Generate QR code
                    qr_base64 = generate_qr_code(sales_invoice, cae, cae_vto)

                    # Update Sales Invoice
                    frappe.db.set_value("Sales Invoice", salesInvoice, {
                        "custom_cae": cae,
                        "custom_caefchvto": cae_vto,
                        "custom_qr_base64": qr_base64,
                        "custom_observations": obs_msg if (hasattr(det_resp, 'Observaciones') and det_resp.Observaciones) else ""
                    })
                    frappe.db.commit()
                    
                    log_electronic_invoice_error(
                        doctype="Sales Invoice", 
                        title=f"Electronic Invoice for {sales_invoice.name} Generated Successfully",
                        status="Success",
                        message = (
                            f"'custom_cae': {cae}, "
                            f"'custom_caefchvto': {cae_vto}, "
                            f"'custom_qr_base64': {qr_base64}, "
                            f"'custom_observations': "
                            f"{obs_msg if (hasattr(det_resp, 'Observaciones') and det_resp.Observaciones) else ''}"
                        )
                    )


                    
                    frappe.msgprint(f"Invoice registered successfully with CAE: {cae}")
                    return {"success": True, "cae": cae, "cae_vto": cae_vto}
                else:
                    frappe.throw(f"AFIP Validation Error: {det_resp.Resultado}")
            else:
                frappe.throw("Invalid response structure from AFIP")

        except Fault as e:
            frappe.throw(f"AFIP Web Service Error: {str(e)}")
            
    except Exception as e:
        error_msg = str(e)
        if not error_msg or error_msg == "0":
            # Get more detailed error information
            detailed_error = {
                "error_type": type(e).__name__,
                "error_args": getattr(e, 'args', []),
                "error_message": str(e),
                "afip_details": {
                    "token_exists": bool(afip_details.token),
                    "sign_exists": bool(afip_details.sign),
                    "cuit_exists": bool(afip_details.cuit)
                }
            }
            error_msg = f"AFIP Webservice Error - Details: {json.dumps(detailed_error, indent=2)}"
        
        frappe.log_error(
            message=f"AFIP Invoice Generation Error:\n{error_msg}\n\nTraceback:\n{traceback.format_exc()}",
            title="AFIP Error - Detailed"
        )
        
        frappe.throw(
            msg=f"Error generating AFIP invoice: {error_msg}. Please check error logs for details.",
            title="AFIP Error"
        )


def get_doc_type(customer):
    """Map customer document types to AFIP types"""
    mapping = {
        "CUIT": 80,
        "DNI": 96,
        "CI": 90
    }
    return mapping.get(customer.custom_customer_document_types, 80)

def get_vat_rate_id(rate):
    """Map VAT rates to AFIP IDs"""
    mapping = {
        21.0: 5,  # 21%
        10.5: 4,  # 10.5%
        27.0: 6   # 27%
    }
    return mapping.get(rate, 5)

def format_afip_errors(errors):
    """Format AFIP error messages with more detailed handling"""
    try:
        if hasattr(errors, 'Err'):
            if isinstance(errors.Err, (list, tuple)):
                return "; ".join([f"Error {err.Code}: {err.Msg}" for err in errors.Err])
            else:
                return f"Error {errors.Err.Code}: {errors.Err.Msg}"
        elif isinstance(errors, (list, tuple)):
            return "; ".join([f"Error {err.Code if hasattr(err, 'Code') else 'Unknown'}: {err.Msg if hasattr(err, 'Msg') else str(err)}" for err in errors])
        else:
            error_dict = {
                'raw_error': str(errors),
                'error_type': type(errors).__name__,
                'has_err': hasattr(errors, 'Err'),
                'error_dir': dir(errors)
            }
            return f"Unstructured Error: {json.dumps(error_dict, indent=2)}"
    except Exception as e:
        return f"Error while formatting AFIP errors: {str(e)}, Raw errors: {str(errors)}"

def get_company_cuit():
    """Fetch CUIT from AFIP Settings
    
    Returns:
        str: Company CUIT number or None if not found
    """
    try:
        afip_settings = frappe.get_single("AFIP Setting")
        if not afip_settings.cuit:
            frappe.log_error(
                message="CUIT not configured in AFIP Settings",
                title="AFIP Configuration Error"
            )
            return None
        return afip_settings.cuit.replace("-", "").strip()
    except Exception as e:
        frappe.log_error(
            message=f"Error fetching CUIT from AFIP Settings: {str(e)}",
            title="AFIP Configuration Error"
        )
        return None

import json
import base64
import urllib.parse
import qrcode
from io import BytesIO

def generate_qr_code(invoice, cae, cae_vto):
    try:
        customer = frappe.get_doc("Customer", invoice.customer)
        # Your existing data preparation code remains the same
        data = {
            "ver": 1,
            "fecha": invoice.posting_date.strftime("%Y-%m-%d"),
            "cuit": int(frappe.db.get_single_value("AFIP Setting", "cuit")),
            "ptoVta": get_pos_number(invoice),
            "tipoCmp": get_invoice_type(invoice),
            "nroCmp": int(invoice.name.split('-')[-1]),
            "importe": float(invoice.grand_total),
            "moneda": "PES",
            "ctz": 1,
            "tipoDocRec": get_doc_type(customer),
            "nroDocRec": _to_int_or_default(customer.tax_id, 0),
            "tipoCodAut": "E",
            "codAut": int(cae)
        }

        # Convert data to JSON and create URL
        json_string = json.dumps(data)
        url_encoded = base64.b64encode(json_string.encode()).decode()
        afip_url = f'https://www.afip.gob.ar/fe/qr/?p={url_encoded}'

        # Create QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        
        # Add the URL to QR code
        qr.add_data(afip_url)
        qr.make(fit=True)

        # Create QR image
        qr_image = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        buffered = BytesIO()
        qr_image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Return with proper data URI prefix
        return f"data:image/png;base64,{img_str}"

    except Exception as e:
        frappe.log_error(
            message=f"QR Code generation error: {str(e)}",
            title="QR Code Error"
        )
        return None

@frappe.whitelist()
def cancel_invoice(salesInvoice):
    try:
        # Get AFIP settings
        afip_details = frappe.get_doc("AFIP Setting")
        if not all([afip_details.token, afip_details.sign, afip_details.cuit]):
            frappe.throw("Missing AFIP credentials. Please check AFIP Settings.")

        # Get sales invoice details
        sales_invoice = frappe.get_doc("Sales Invoice", salesInvoice)
        customer = frappe.get_doc("Customer", sales_invoice.customer)

        # Get invoice type and POS number
        original_invoice_type = get_invoice_type(sales_invoice)
        pos_number = get_pos_number(sales_invoice)

        # Initialize WSFE client
        client = get_afip_client(afip_details)

        # Create authentication header
        auth = {
            'Token': afip_details.token.strip(),
            'Sign': afip_details.sign.strip(),
            'Cuit': int(afip_details.cuit)
        }

        # Log starting state
        frappe.log_error(
            message=f"Starting credit note generation for invoice: {salesInvoice}",
            title="AFIP Credit Note - Start"
        )

        # Verify CAE exists
        if not getattr(sales_invoice, 'custom_cae', None):
            frappe.throw("This invoice has not been authorized by AFIP yet. Please ensure it has a valid CAE before cancellation.")

        # Map invoice types to credit note types
        credit_note_type_mapping = {
            1: 3,   # Factura A -> Nota de Crédito A
            6: 8,   # Factura B -> Nota de Crédito B
            11: 13  # Factura C -> Nota de Crédito C
        }
        credit_note_type = credit_note_type_mapping.get(original_invoice_type)
        
        if not credit_note_type:
            frappe.throw(f"Unsupported invoice type for credit note: {original_invoice_type}")

        # Get next credit note number
        last_credit_note = get_last_authorized_invoice(client, auth, pos_number, credit_note_type)
        next_credit_note_number = last_credit_note + 1

        # Calculate amounts
        total_amount = abs(float(sales_invoice.grand_total))
        net_amount = abs(float(sales_invoice.net_total))
        vat_amount = abs(float(sales_invoice.total_taxes_and_charges))
        vat_rate = 21.0  # Default VAT rate
        for tax in sales_invoice.taxes:
            if tax.rate > 0:
                vat_rate = abs(tax.rate)
                break

        # Create request data structure
        CbteAsoc = client.get_type('ns0:CbteAsoc')
        ArrayOfCbteAsoc = client.get_type('ns0:ArrayOfCbteAsoc')
        AlicIva = client.get_type('ns0:AlicIva')
        ArrayOfAlicIva = client.get_type('ns0:ArrayOfAlicIva')

        # Create associated invoice array
        original_number = extract_invoice_number(sales_invoice.name, original_invoice_type)
        cbte_asoc = CbteAsoc(
            Tipo=original_invoice_type,
            PtoVta=pos_number,
            Nro=original_number
        )
        cbtes_asoc_array = ArrayOfCbteAsoc([cbte_asoc])

        # Create IVA array
        alic_iva = AlicIva(
            Id=get_vat_rate_id(vat_rate),
            BaseImp=round(net_amount, 2),
            Importe=round(vat_amount, 2)
        )
        array_alic_iva = ArrayOfAlicIva([alic_iva])

        # Create full request
        request_data = {
            'Auth': auth,
            'FeCAEReq': {
                'FeCabReq': {
                    'CantReg': 1,
                    'PtoVta': pos_number,
                    'CbteTipo': credit_note_type
                },
                'FeDetReq': {
                    'FECAEDetRequest': [{
                        'Concepto': 1,
                        'DocTipo': get_doc_type(customer),
                        'DocNro': _to_int_or_default(customer.tax_id, 0),
                        'CbteDesde': next_credit_note_number,
                        'CbteHasta': next_credit_note_number,
                        'CbteFch': datetime.now().strftime('%Y%m%d'),
                        'ImpTotal': round(total_amount, 2),
                        'ImpTotConc': 0.0,
                        'ImpNeto': round(net_amount, 2),
                        'ImpOpEx': 0.0,
                        'ImpIVA': round(vat_amount, 2),
                        'ImpTrib': 0.0,
                        'MonId': 'PES',
                        'MonCotiz': 1.0,
                        'CbtesAsoc': cbtes_asoc_array,
                        'Iva': array_alic_iva
                    }]
                }
            }
        }

        # Log request data
        frappe.log_error(
            message=f"Credit Note Request:\n{json.dumps(request_data, indent=2, default=str)}",
            title="AFIP Credit Note - Request"
        )

        try:
            # Request CAE for credit note
            response = client.service.FECAESolicitar(**request_data)
            
            if (hasattr(response, 'FeDetResp') and 
                hasattr(response.FeDetResp, 'FECAEDetResponse')):
                
                det_resp = response.FeDetResp.FECAEDetResponse[0]
                
                if det_resp.Resultado == 'A' and det_resp.CAE:
                    credit_note_cae = det_resp.CAE
                    credit_note_cae_vto = det_resp.CAEFchVto
                    
                    # Generate QR code
                    qr_base64 = generate_qr_code(sales_invoice, credit_note_cae, credit_note_cae_vto)

                    # Update only the necessary fields
                    update_fields = {
                        "custom_cae": credit_note_cae,
                        "custom_caefchvto": credit_note_cae_vto,
                        "custom_qr_base64": qr_base64
                    }

                    # Update the invoice with only existing fields
                    for field, value in update_fields.items():
                        try:
                            frappe.db.set_value("Sales Invoice", salesInvoice, field, value)
                        except Exception as field_error:
                            frappe.log_error(
                                message=f"Failed to update field {field}: {str(field_error)}",
                                title="Field Update Error"
                            )
                    
                    frappe.db.commit()
                    
                    frappe.msgprint("Credit note generated successfully with CAE: " + credit_note_cae)
                    return {
                        "success": True,
                        "credit_note_number": next_credit_note_number,
                        "cae": credit_note_cae,
                        "cae_vto": credit_note_cae_vto
                    }
                else:
                    error_msg = "AFIP Validation Error"
                    if hasattr(det_resp, 'Observaciones'):
                        obs = det_resp.Observaciones.Obs
                        if isinstance(obs, list):
                            error_msg += ": " + "; ".join([f"{o.Code}: {o.Msg}" for o in obs])
                        else:
                            error_msg += f": {obs.Code}: {obs.Msg}"
                    frappe.throw(error_msg)
            else:
                frappe.throw("Invalid response structure from AFIP")

        except Exception as e:
            frappe.log_error(
                message=f"AFIP Credit Note Error:\n{str(e)}\n\nTraceback:\n{traceback.format_exc()}",
                title="AFIP Credit Note - Error"
            )
            frappe.throw(f"Error processing credit note: {str(e)}")
            
    except Exception as e:
        frappe.log_error(
            message=f"Credit Note Generation Failed:\n{str(e)}\n\nTraceback:\n{traceback.format_exc()}",
            title="Credit Note - Fatal Error"
        )
        frappe.throw(f"Failed to generate credit note: {str(e)}")