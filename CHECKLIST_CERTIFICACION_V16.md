# Checklist de Certificacion E2E - Argentina Compliance (Frappe/ERPNext v16)

## Objetivo
Validar compatibilidad real operativa de la app en v16, incluyendo AFIP WSAA/WSFE, datos maestros, UX y trazabilidad.

## Pre-condiciones
- Site con Frappe/ERPNext v16 actualizado.
- App instalada en rama propia: `gefai/version-16-hardening`.
- AFIP Setting configurado con:
  - `cuit`
  - `use_sandbox_environment`
  - certificado y clave privada validos
- Cliente de prueba con `tax_id`, `custom_vat_status`, `custom_customer_document_types`.
- Item e impuestos configurados para IVA 21% y 10.5%.

## 1. Sanidad Tecnica
- [ ] `bench version` muestra Frappe/ERPNext v16 y app en rama propia.
- [ ] `bench --site <site> migrate` sin errores.
- [ ] `bench --site <site> clear-cache` y `bench --site <site> clear-website-cache`.
- [ ] Validar existencia de custom fields en Customer, Company y Sales Invoice.

## 2. Token AFIP (WSAA)
- [ ] Ejecutar renovacion manual de token.
- [ ] Verificar que se guarda `token` y `sign` en AFIP Setting.
- [ ] Confirmar que no falla por rutas/certificados/openssl.
- [ ] Confirmar que scheduler renueva token sin errores en logs.

## 3. Factura Electronica (WSFE)
- [ ] Crear Sales Invoice normal (no return), con customer completo.
- [ ] Presionar boton Generate E-Invoice.
- [ ] Confirmar:
  - [ ] `custom_cae` informado
  - [ ] `custom_caefchvto` informado
  - [ ] `custom_qr_base64` informado
  - [ ] `custom_observations` manejado cuando AFIP devuelve observaciones
- [ ] Validar correlatividad AFIP (numero comprobante esperado).

## 4. Nota de Credito
- [ ] Crear una devolucion (`is_return=1`) sobre factura autorizada.
- [ ] Presionar boton Generate Credit Note.
- [ ] Confirmar CAE y vencimiento de CAE para NC.
- [ ] Confirmar asociacion con comprobante original en AFIP.

## 5. Validaciones de Datos (regresiones criticas)
- [ ] POS:
  - [ ] Funciona con `custom_point_of_sale` numerico
  - [ ] Funciona cuando `pos_profile` no es numerico (fallback seguro)
- [ ] Documento receptor:
  - [ ] CUIT con guiones se normaliza correctamente
  - [ ] Si falta documento, no rompe con excepcion de casteo
- [ ] Condicion IVA receptor:
  - [ ] Se envia como ID numerico valido al WSFE

## 6. Logs y Trazabilidad
- [ ] Revisar Error Log y Electronic Invoice Log despues de cada caso.
- [ ] Verificar mensajes de error accionables (sin errores ambiguos tipo "0").
- [ ] Confirmar que no quedan commits manuales pendientes por transacciones fallidas.

## 7. Pruebas de Concurrencia Basica
- [ ] Emitir 2 facturas seguidas del mismo POS/tipo.
- [ ] Confirmar correlatividad sin colisiones ni duplicados.

## 8. Criterios de Aprobacion
- [ ] 100% de casos criticos aprobados (token, factura, NC, QR).
- [ ] Cero errores bloqueantes en logs durante 48 horas.
- [ ] Equipo operativo puede emitir/cancelar sin soporte tecnico.

## Comandos Utiles
```bash
bench version
bench --site <site> migrate
bench --site <site> clear-cache
bench --site <site> execute argentina_compliance.argentina_compliance.doc_events.afip_token.get_afip_token
```
