@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo.
echo  === Atualizar horarios ===
echo.

python extrair.py
if errorlevel 1 (
  echo.
  echo  [ERRO] A recolha falhou. Nada foi publicado.
  pause
  exit /b 1
)

git diff --quiet -- dados.json
if not errorlevel 1 (
  echo.
  echo  Nada a publicar: o site ja tem estes horarios.
  pause
  exit /b 0
)

echo.
echo  A publicar no GitHub...
git add dados.json
git commit -m "Atualizar horarios" > nul
git push -u origin main
if errorlevel 1 (
  echo.
  echo  [ERRO] O envio falhou. Verifica a ligacao ou as credenciais do Git.
  pause
  exit /b 1
)

echo.
echo  Pronto. O site fica atualizado dentro de um minuto.
echo.
pause
