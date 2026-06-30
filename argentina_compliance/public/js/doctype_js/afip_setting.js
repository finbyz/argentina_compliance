// // For child table: Credentials
// frappe.ui.form.on('Credentials', {
//     company: function( cdt, cdn) {
//         console.log("hello")
//         let row = locals[cdt][cdn];
//         if (row.company) {
//             frappe.db.get_value('Company', row.company, 'custom_cuit')
//                 .then(r => {
//                     if (r.message && r.message.custom_cuit) {
//                         frappe.model.set_value(cdt, cdn, 'cuit', r.message.custom_cuit);
//                     }
//                 });
//         } else {
//             frappe.model.set_value(cdt, cdn, 'cuit', '');
//         }
//     },

//     // Also trigger when the row loads (e.g., company auto-set)
//     company_name: function(frm, cdt, cdn) {
//         frappe.ui.form.trigger('Credentials', 'company', frm, cdt, cdn);
//     },

//     // Or you can also handle on form refresh (auto-fill CUIT for all rows)
//     refresh: function(frm) {
//         (frm.doc.credentials || []).forEach(row => {
//             if (row.company && !row.cuit) {
//                 frappe.db.get_value('Company', row.company, 'custom_cuit')
//                     .then(r => {
//                         if (r.message && r.message.custom_cuit) {
//                             frappe.model.set_value(row.doctype, row.name, 'cuit', r.message.custom_cuit);
//                         }
//                     });
//             }
//         });
//     }
// });


// This script would be attached to the 'Sales Invoice' DocType
frappe.ui.form.on("AFIP Setting", {
    refresh(frm) {
        frm.add_custom_button(__("Generate New Token"), () => {
            frappe.call({
                method: "argentina_compliance.argentina_compliance.doctype.afip_setting.afip_setting.generate_new_token",
                freeze: true,
                freeze_message: __("Generating a new AFIP token..."),
                callback: () => {
                    frappe.msgprint({
                        title: __("AFIP Token"),
                        indicator: "green",
                        message: __("A new AFIP token/sign was generated successfully."),
                    });
                    frm.reload_doc();
                },
            });
        }, __("Actions"));

        frm.add_custom_button(__("Test WSFE Connection"), () => {
            frappe.prompt(
                [
                    {
                        fieldname: "pos_number",
                        label: __("POS Number (optional)"),
                        fieldtype: "Int",
                        reqd: 0,
                    },
                    {
                        fieldname: "invoice_type",
                        label: __("Invoice Type (optional)"),
                        fieldtype: "Int",
                        reqd: 0,
                    },
                    {
                        fieldname: "force_new_token",
                        label: __("Force New Token"),
                        fieldtype: "Check",
                        default: 0,
                    },
                ],
                (values) => {
                    frappe.call({
                        method: "argentina_compliance.argentina_compliance.doctype.afip_setting.afip_setting.test_wsfe_connection",
                        args: {
                            pos_number: values.pos_number || null,
                            invoice_type: values.invoice_type || null,
                            force_new_token: values.force_new_token || 0,
                        },
                        freeze: true,
                        freeze_message: __("Testing AFIP WSFE connection..."),
                        callback: (r) => {
                            const data = r.message || {};
                            let message = [
                                `<b>${__("Environment")}:</b> ${data.environment || "-"}`,
                                `<b>${__("Token Source")}:</b> ${data.token_source || "-"}`,
                                `<b>${__("Token Valid")}</b>: ${data.token_valid ? __("Yes") : __("No")}`,
                                `<b>${__("AppServer")}</b>: ${data.dummy?.app_server || "-"}`,
                                `<b>${__("DbServer")}</b>: ${data.dummy?.db_server || "-"}`,
                                `<b>${__("AuthServer")}</b>: ${data.dummy?.auth_server || "-"}`,
                            ];

                            if (data.last_authorized) {
                                message.push(
                                    `<b>${__("Last Authorized Invoice")}</b>: ${data.last_authorized.number} ` +
                                    `(POS ${data.last_authorized.pos_number}, Type ${data.last_authorized.invoice_type})`
                                );
                            } else {
                                message.push(
                                    `<b>${__("Note")}</b>: ${__("FEDummy validates WSFE availability only. It does not validate CUIT/token authorization.")}`
                                );
                                message.push(
                                    `${__("To validate credentials, use 'Force New Token' or enter POS + Invoice Type.")}`
                                );
                            }

                            frappe.msgprint({
                                title: __("WSFE Connection Successful"),
                                indicator: "green",
                                message: message.join("<br>"),
                            });
                        },
                    });
                },
                __("Test AFIP Connection"),
                __("Run Test")
            );
        }, __("Actions"));
    },
});

frappe.ui.form.on("Credentials", {
    company: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        console.log("hello")
        if (row.company) {
            frappe.db.get_value("Company", {"name": row.company}, "custom_cuit")
                .then(r => {
                    if (r.message && r.message.custom_cuit) {
                        frappe.model.set_value(cdt, cdn, "cuit", r.message.custom_cuit);
                    } else {
                        frappe.model.set_value(cdt, cdn, "cuit", "");
                    }
                });
        } else {
            frappe.model.set_value(cdt, cdn, "cuit", "");
        }
    }
});

