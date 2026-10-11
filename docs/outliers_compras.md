# Outliers conocidos en compras OCDS

## UTE × STILER S A — ocds-yfs5dr-1318822 (jul 2026)
`total_value` = $623.750.258.522 (623 mil millones) — deriva de 1 item:
quantity 1.200.007 × unit.value 519.788,85 USD ("ARRENDAMIENTO EQUIPOS DE GENERACION").
Es literalmente lo que reporta el release OCDS de ARCE (award sin value agregado;
el importe sale de sumar items quantity×price). Probablemente UTE reporta el contrato
multi-año (unit-price × periodos) o un error de carga de UTE en el SARCO/ARCE.
**Efecto**: distorsiona `compras_estadisticas(anio=2026)` y top proveedores 2026
(sin este registro 2026 suma ~$14 mil millones). Tratar como outlier de fuente,
NO como gasto consolidado. Revisar el detalle en comprasestatales.gub.uy (ocid)
antes de citar el total 2026.

Chequeo rápido si vuelve a aparecer:
```sql
SELECT ocds_id, supplier_names, buyer_name, total_value FROM compras WHERE anio=2026 ORDER BY total_value DESC LIMIT 5;
```
