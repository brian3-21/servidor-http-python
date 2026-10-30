# Servidor HTTP desde cero

Curso práctico: vas a construir un servidor HTTP real en Python, usando **solo la librería estándar**. Sin Flask, sin FastAPI, sin frameworks. Al final entenderás qué hace un servidor por dentro y por qué existen esas herramientas.

## Requisitos

- Python 3.10 o superior. Tienes 3.12.3: sobra. La última estable es 3.15, pero el curso solo usa cosas disponibles desde 3.10, así que no hace falta actualizar.
- Un terminal y ganas de escribir código.

## Estructura

```
servidor/     ← tu código (aquí trabajas)
pruebas/      ← verificador de caja negra (no lo toques)
public/       ← archivos estáticos de prueba
notas/        ← apuntes del profesor
progreso.md   ← tu estado por hito
```

## Cómo se avanza

1. Abre OpenCode en esta carpeta.
2. Ejecuta `/leccion` (cambia solo al agente Maestro).
3. Intenta la tarea. Cuando termines, el profesor ejecuta el verificador:

```bash
python3 pruebas/verificar.py m1
```

El verificador arranca tu servidor, le habla por TCP y comprueba el comportamiento. Te dice **qué** falla, no **cómo** arreglarlo.

## El contrato del proyecto

| Método | Ruta | Respuesta |
|---|---|---|
| GET | `/hola` | 200, HTML, cuerpo `Hola` |
| GET | `/` | 200, `public/index.html` |
| GET | `/estilo.css` | 200, `text/css` |
| GET | `/saludo` | 200, cuerpo con `Hola` |
| GET | `/api/hora` | 200, JSON con la hora |
| POST | `/api/eco` | 200, devuelve el JSON recibido |
| GET | `/lento` | 200 tras ~1 s |
| — | ruta desconocida | 404 |
| POST | `/saludo` | 405 |

## Comandos útiles

```bash
python3 servidor/main.py            # arrancar tu servidor (Ctrl+C para parar)
python3 pruebas/verificar.py m4     # comprobar el hito 4
curl -i http://127.0.0.1:8000/hola  # ver la respuesta cruda
```

Si el puerto 8000 está ocupado, cierra el servidor que dejaste abierto antes de ejecutar el verificador.

## Regla del curso

El profesor no te va a dar el código. Te va a hacer preguntas hasta que lo escribas tú. Si te atascas, `/pista` da una sola pista. Si quieres que revise algo, `/revisar`.
