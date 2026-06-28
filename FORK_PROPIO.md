# Fork Propio - Pasos Rapidos

## Estado actual
- Rama local creada: `gefai/version-16-hardening`
- Cambios de hardening aplicados para v16

## Opcion A (recomendada): con GitHub CLI
Si tenes `gh` instalado y autenticado:

```bash
cd /home/gefai/frappe-bench/apps/argentina_compliance
gh auth login
gh repo fork --remote=true --clone=false
git push -u origin gefai/version-16-hardening
```

## Opcion B: desde web + git
1. Hacer Fork en GitHub (boton Fork).
2. Reemplazar `origin` por tu fork:

```bash
cd /home/gefai/frappe-bench/apps/argentina_compliance
git remote rename origin upstream
git remote add origin <URL_DE_TU_FORK>
git push -u origin gefai/version-16-hardening
```

## Politica sugerida
- `upstream`: repo original
- `origin`: tu fork
- rama base de mantenimiento: `gefai/version-16-hardening`
- Pull Requests internos hacia ramas release propias (`gefai/version-16`, `gefai/prod`)
