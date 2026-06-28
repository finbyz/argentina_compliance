# Resultado Corrida E2E - 2026-06-28

Site: `gefai.com.ar`
Branch app: `gefai/version-16-hardening` (commit `b9ee8ea`)

## 1. Sanidad Tecnica
- [x] `bench version` valida Frappe/ERPNext v16 y rama hardening de app.
- [x] `bench --site gefai.com.ar migrate` exitoso.
- [x] `clear-cache` y `clear-website-cache` ejecutados.
- [x] Custom fields de Argentina Compliance presentes en Customer, Company y Sales Invoice.

## 2. Token AFIP (WSAA)
- [ ] Renovacion manual de token: BLOQUEADO.
  - Error: falta archivo de certificado en AFIP Setting.
  - Estado AFIP Setting en DB: no hay valores de `cuit`, `certificate`, `private_key`, `token`, `sign`.
- [x] Parche aplicado para usar archivos adjuntos reales del AFIP Setting (`certificate` y `private_key`) en lugar de nombres hardcodeados.

## 3. Factura Electronica (WSFE)
- [ ] BLOQUEADO por precondicion WSAA (sin token/sign por falta de certificado y clave).

## 4. Nota de Credito
- [ ] BLOQUEADO por precondicion WSAA/WSFE.

## 5. Validaciones de Datos
- [x] Parche POS/fallback implementado (`custom_point_of_sale` -> `pos_profile` -> `1`).
- [x] Parche para normalizacion de DocNro/CUIT implementado.
- [x] Parche para Condicion IVA receptor como ID numerico implementado.
- [ ] Validacion funcional final pendiente de ejecutar (requiere token AFIP operativo).

## 6. Logs y Trazabilidad
- [x] Revisados logs recientes.
- [ ] Validacion post-emision/NC pendiente (cuando WSAA este operativo).

## 7. Concurrencia Basica
- [ ] Pendiente (requiere emision AFIP operativa).

## Acciones requeridas para desbloquear
1. Configurar AFIP Setting en el sitio `gefai.com.ar`:
   - `cuit`
   - `use_sandbox_environment`
   - `certificate` (Attach)
   - `private_key` (Attach)
2. Re-ejecutar:
   - `bench --site gefai.com.ar execute "argentina_compliance.argentina_compliance.doc_events.afip_token.get_afip_token"`
3. Ejecutar tramo funcional del checklist (factura, NC, correlatividad, logs).

## Datos maestros observados
- Clientes detectados (`Tucan`, `PedidosYA`) tienen `custom_vat_status`, pero `tax_id` nulo.
- Se detecta al menos una configuracion de IVA 21% (`Argentina Tax - Alcira`).
