# Horários — DEI — ULO

Horários dos cursos do Departamento de Engenharia Informática da Universidade
Leiria·Oeste, ano letivo 2026/2027.

**https://diasjairo.github.io/horarios-dei-ulo/**

## O que faz

Mostra os horários publicados pela escola e permite montar horários próprios,
escolhendo as unidades curriculares e deixando a aplicação calcular todas as
combinações de turnos possíveis sem sobreposições. As combinações podem ser
ordenadas e filtradas por número de dias de aulas, tempo de espera entre aulas,
hora de início e de fim, e dias a evitar.

Funciona em computador e telemóvel, permite guardar horários para comparar e
imprimir a grelha em A4.

## Ficheiros

| Ficheiro | Descrição |
|---|---|
| `index.html` | A aplicação. Não depende de nada externo. |
| `dados.json` | Os horários. Gerado pelo extrator. |
| `extrair.py` | Recolhe os horários do portal e escreve o `dados.json`. |
| `cursos.txt` | Que cursos incluir. Uma linha por curso, `#` para excluir. |
| `atualizar.bat` | Recolhe e publica, num passo. |

## Atualizar

```
python extrair.py     # só escreve se os horários tiverem mudado
```

Ou, para recolher e publicar de uma vez, executar o `atualizar.bat`.

Para ver todos os cursos disponíveis no portal:

```
python extrair.py --listar
```

Requer Python 3.8 ou superior. Não usa bibliotecas externas.
