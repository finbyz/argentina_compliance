# Copyright (c) 2024, Finbyz Tech Pvt Ltd and contributors
# For license information, please see license.txt

import json
import frappe
import traceback
from frappe.model.document import Document
from frappe.utils import cint
from zeep import Client
from argentina_compliance.argentina_compliance.doc_events.afip_token import (
    get_afip_token,
    check_token_validity
)


class AFIPSetting(Document):
    def validate(self):
        # If CUIT changes, previously issued token/sign may no longer be valid
        # for the configured identity. Clear them to prevent stale auth usage.
        old_cuit = frappe.db.get_single_value("AFIP Setting", "cuit")
        current_cuit = (self.get("cuit") or "").strip()
        if old_cuit and current_cuit and str(old_cuit).strip() != current_cuit:
            self.token = ""
            self.sign = ""

        # Backward compatibility: newer schemas may not define a credentials child table.
        credentials = getattr(self, "credentials", None) or []
        if not credentials:
            return

        # validate company not set duplicate
        seen = {}
        for row in credentials:
            if not getattr(row, "company", None):
                continue

            if row.company in seen:
                frappe.throw(
                    f"Duplicate company '{row.company}' found in Row {row.idx} "
                    f"(already used in Row {seen[row.company]})"
                )
            seen[row.company] = row.idx
    
    

@frappe.whitelist()
def create_new_token(row):
    row = json.loads(row)
    return get_afip_token(force_new=1)


@frappe.whitelist()
def generate_new_token():
    """Generate a fresh AFIP token/sign regardless of current cached validity."""
    return get_afip_token(force_new=1)


def _get_wsfe_wsdl(use_sandbox_environment):
    if cint(use_sandbox_environment):
        return "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL"
    return "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL"


@frappe.whitelist()
def test_wsfe_connection(pos_number=None, invoice_type=None, force_new_token=0):
    """Test AFIP WSFE connectivity.

    Performs a lightweight connectivity check with FEDummy and, optionally,
    retrieves the last authorized invoice number for a POS/invoice type.
    """
    try:
        afip_settings = frappe.get_doc("AFIP Setting")

        if not afip_settings.cuit:
            frappe.throw("AFIP Setting requires CUIT before testing connection.")

        client = Client(_get_wsfe_wsdl(afip_settings.use_sandbox_environment))

        dummy = client.service.FEDummy()
        has_token = bool(afip_settings.token and afip_settings.sign)
        token_valid = check_token_validity() if has_token else False

        if cint(force_new_token):
            get_afip_token(force_new=1)
            afip_settings.reload()
            has_token = bool(afip_settings.token and afip_settings.sign)
            token_valid = check_token_validity() if has_token else False

        result = {
            "success": True,
            "environment": "sandbox" if cint(afip_settings.use_sandbox_environment) else "production",
            "token_source": "refreshed" if cint(force_new_token) else ("existing" if has_token else "missing"),
            "token_valid": token_valid,
            "dummy": {
                "app_server": getattr(dummy, "AppServer", None),
                "db_server": getattr(dummy, "DbServer", None),
                "auth_server": getattr(dummy, "AuthServer", None),
            },
        }

        if pos_number and invoice_type:
            if not has_token or not token_valid:
                if not has_token or not token_valid:
                    frappe.throw(
                        "WSFE is reachable (FEDummy OK), but a valid AFIP token/sign is required "
                        "to fetch last invoice. Enable 'Force New Token' or generate token first."
                    )

            auth = {
                "Token": afip_settings.token.strip(),
                "Sign": afip_settings.sign.strip(),
                "Cuit": int(str(afip_settings.cuit).replace("-", "").strip()),
            }

            last = client.service.FECompUltimoAutorizado(
                auth,
                cint(pos_number),
                cint(invoice_type),
            )

            if getattr(last, "Errors", None):
                err = last.Errors
                if getattr(err, "Err", None):
                    if isinstance(err.Err, (list, tuple)):
                        detail = "; ".join([f"{e.Code}: {e.Msg}" for e in err.Err])
                    else:
                        detail = f"{err.Err.Code}: {err.Err.Msg}"
                else:
                    detail = str(err)
                frappe.throw(f"WSFE connected but FECompUltimoAutorizado failed: {detail}")

            result["last_authorized"] = {
                "pos_number": cint(pos_number),
                "invoice_type": cint(invoice_type),
                "number": getattr(last, "CbteNro", None),
            }

        return result

    except Exception as e:
        if isinstance(e, frappe.ValidationError):
            raise

        frappe.log_error(
            message=f"WSFE connection test failed: {str(e)}\n\n{traceback.format_exc()}",
            title="AFIP WSFE Connection Test Error",
        )
        frappe.throw(f"AFIP WSFE connection test failed: {str(e)}")