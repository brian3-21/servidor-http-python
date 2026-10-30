#!/usr/bin/env python3
"""Verificador de caja negra del curso «Servidor HTTP desde cero».

Uso:
    python3 pruebas/verificar.py m4

Arranca tu servidor, le habla por TCP y comprueba comportamiento observable.
No contiene la solución: dice qué falla, no cómo arreglarlo.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "servidor" / "main.py"
HOST = "127.0.0.1"
PUERTO = 8000
TIMEOUT = 2.0


class Fallo(Exception):
    """Una comprobación no se cumplió."""


class Omitido(Exception):
    """Comprobación opcional que no aplica."""


# ---------------------------------------------------------------------------
# Infraestructura
# ---------------------------------------------------------------------------


def exigir(condicion: bool, mensaje: str) -> None:
    if not condicion:
        raise Fallo(mensaje)


def puerto_ocupado() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((HOST, PUERTO)) == 0


def escuchando() -> bool:
    """Mira /proc/net/tcp para no abrir una conexión de prueba."""
    objetivo = f":{PUERTO:04X}"
    for ruta in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(ruta, encoding="ascii") as f:
                next(f, None)
                for linea in f:
                    campos = linea.split()
                    if len(campos) > 3 and campos[1].endswith(objetivo) and campos[3] == "0A":
                        return True
        except OSError:
            continue
    # Sin /proc disponible: conexión de prueba (menos fiable).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.1)
        return s.connect_ex((HOST, PUERTO)) == 0


class Servidor:
    def __init__(self) -> None:
        fd, ruta = tempfile.mkstemp(prefix="servidor-http-", suffix=".log")
        os.close(fd)
        self.log_path = Path(ruta)
        self.proc: subprocess.Popen[bytes] | None = None
        self._fh = None

    def arrancar(self) -> None:
        if not SERVIDOR.exists():
            raise Fallo("no existe servidor/main.py")
        for _ in range(100):
            if not puerto_ocupado():
                break
            time.sleep(0.1)
        else:
            raise Fallo(
                "el puerto 8000 está ocupado. Cierra el servidor que dejaste abierto "
                "y vuelve a intentarlo."
            )

        self._fh = open(self.log_path, "wb")
        entorno = os.environ.copy()
        entorno["PYTHONUNBUFFERED"] = "1"
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVIDOR)],
            cwd=RAIZ,
            stdout=self._fh,
            stderr=subprocess.STDOUT,
            env=entorno,
            start_new_session=True,
        )
        for _ in range(80):
            if self.proc.poll() is not None:
                raise Fallo("el servidor terminó al arrancar:\n" + self.salida()[-1500:])
            if escuchando():
                return
            time.sleep(0.1)
        raise Fallo("el servidor no se puso a escuchar en el puerto 8000 en 8 s")

    def salida(self) -> str:
        if self._fh is not None:
            try:
                self._fh.flush()
            except ValueError:
                pass
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def cerrar(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        try:
            self.log_path.unlink(missing_ok=True)
        except OSError:
            pass


def _leer(s: socket.socket, limite: float) -> bytes:
    """Lee una respuesta HTTP sin quedarse colgado si el servidor no cierra."""
    s.settimeout(limite)
    datos = b""

    while b"\r\n\r\n" not in datos:
        try:
            trozo = s.recv(65536)
        except socket.timeout:
            return datos
        if not trozo:
            return datos
        datos += trozo

    cabeza, _, resto = datos.partition(b"\r\n\r\n")
    cabeceras: dict[str, str] = {}
    for linea in cabeza.split(b"\r\n")[1:]:
        if b":" in linea:
            clave, valor = linea.split(b":", 1)
            cabeceras[clave.strip().decode("latin-1").lower()] = valor.strip().decode("latin-1")

    if "content-length" in cabeceras:
        try:
            total = int(cabeceras["content-length"])
        except ValueError:
            total = 0
        cuerpo = resto
        while len(cuerpo) < total:
            try:
                trozo = s.recv(65536)
            except socket.timeout:
                break
            if not trozo:
                break
            cuerpo += trozo
        return cabeza + b"\r\n\r\n" + cuerpo[:total]

    if cabeceras.get("transfer-encoding", "").lower() == "chunked":
        while not resto.endswith(b"0\r\n\r\n"):
            try:
                trozo = s.recv(65536)
            except socket.timeout:
                break
            if not trozo:
                break
            resto += trozo
        return cabeza + b"\r\n\r\n" + resto

    if cabeceras.get("connection", "").lower() == "close":
        while True:
            try:
                trozo = s.recv(65536)
            except socket.timeout:
                break
            if not trozo:
                break
            resto += trozo
        return cabeza + b"\r\n\r\n" + resto

    return cabeza + b"\r\n\r\n" + resto


def peticion(crudo: bytes, timeout: float = TIMEOUT) -> bytes:
    try:
        with socket.create_connection((HOST, PUERTO), timeout=timeout) as s:
            s.sendall(crudo)
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            return _leer(s, timeout)
    except ConnectionRefusedError:
        raise Fallo("el servidor no acepta conexiones (¿se ha caído?)")
    except socket.timeout:
        raise Fallo(f"el servidor no respondió en {timeout:.1f} s")


def peticion_http(
    metodo: str,
    ruta: str,
    cuerpo: bytes = b"",
    cabeceras: dict[str, str] | None = None,
    timeout: float = TIMEOUT,
) -> bytes:
    cab: dict[str, str] = {"Host": "127.0.0.1:8000", "Connection": "close"}
    if cabeceras:
        cab.update(cabeceras)
    if cuerpo and "Content-Length" not in cab:
        cab["Content-Length"] = str(len(cuerpo))
    if metodo in ("POST", "PUT", "PATCH") and "Content-Length" not in cab:
        cab["Content-Length"] = "0"
    lineas = [f"{metodo} {ruta} HTTP/1.1"] + [f"{k}: {v}" for k, v in cab.items()]
    return peticion(("\r\n".join(lineas) + "\r\n\r\n").encode("latin-1") + cuerpo, timeout=timeout)


def separar(respuesta: bytes) -> tuple[str, dict[str, str], bytes]:
    if not respuesta:
        raise Fallo("respuesta vacía: el servidor no envió nada")
    cabeza, separador, cuerpo = respuesta.partition(b"\r\n\r\n")
    if not separador:
        muestra = respuesta[:80].decode("latin-1", errors="replace")
        raise Fallo(f"falta la línea en blanco \\r\\n\\r\\n entre cabeceras y cuerpo (llegó: {muestra!r})")
    lineas = cabeza.split(b"\r\n")
    estado = lineas[0].decode("latin-1").strip()
    cabeceras: dict[str, str] = {}
    for linea in lineas[1:]:
        if b":" in linea:
            clave, valor = linea.split(b":", 1)
            cabeceras[clave.strip().decode("latin-1").lower()] = valor.strip().decode("latin-1")
    return estado, cabeceras, cuerpo


def codigo(estado: str) -> str:
    partes = estado.split()
    if len(partes) < 2:
        raise Fallo(f"línea de estado rara: {estado!r}")
    return partes[1]


def leer_json(cuerpo: bytes):
    try:
        return json.loads(cuerpo)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise Fallo(f"el cuerpo no es JSON válido ({e})")


# ---------------------------------------------------------------------------
# Hito 0
# ---------------------------------------------------------------------------


def m0_existe(_srv) -> None:
    exigir(SERVIDOR.exists(), "no existe servidor/main.py")


def m0_compila(_srv) -> None:
    resultado = subprocess.run(
        [sys.executable, "-m", "py_compile", str(SERVIDOR)],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        ultima = resultado.stderr.strip().splitlines()
        raise Fallo("el archivo no compila: " + (ultima[-1] if ultima else "error de sintaxis"))


def m0_estructura(_srv) -> None:
    for relativo in ("public/index.html", "public/estilo.css", "pruebas/verificar.py", "README.md"):
        exigir((RAIZ / relativo).exists(), f"falta {relativo}")


# ---------------------------------------------------------------------------
# Hito 1
# ---------------------------------------------------------------------------


def m1(srv: Servidor) -> None:
    respuesta = peticion(b"PRUEBA-M1\n", timeout=1.2)
    time.sleep(0.2)
    exigir("PRUEBA-M1" in srv.salida(), "no veo en la salida lo que envié; ¿estás imprimiendo lo que recibes?")
    exigir(b"hola" in respuesta.lower(), f"esperaba una respuesta con 'hola' y llegó {respuesta[:60]!r}")


# ---------------------------------------------------------------------------
# Hito 2
# ---------------------------------------------------------------------------


def m2(srv: Servidor) -> None:
    peticion_http("GET", "/hola", timeout=1.0)
    time.sleep(0.3)
    salida = srv.salida()
    exigir("GET /hola HTTP/1.1" in salida, "no veo la línea de petición completa en la salida")
    exigir("host:" in salida.lower(), "no veo el header Host en la salida")


# ---------------------------------------------------------------------------
# Hito 3
# ---------------------------------------------------------------------------


def m3_parsea(srv: Servidor) -> None:
    peticion_http(
        "GET",
        "/ruta-m3?x=1",
        cabeceras={"Host": "prueba.local", "X-Test": "123"},
        timeout=1.0,
    )
    time.sleep(0.3)
    salida = srv.salida()
    exigir("--> GET /ruta-m3?x=1 HTTP/1.1" in salida, "no veo la línea '--> GET /ruta-m3?x=1 HTTP/1.1'")
    exigir("host: prueba.local" in salida.lower(), "no veo el header Host parseado como 'clave: valor'")


def m3_sobrevive(srv: Servidor) -> None:
    peticion(b"ESTO NO ES HTTP\r\n\r\n", timeout=0.8)
    time.sleep(0.2)
    peticion_http("GET", "/hola", timeout=1.0)
    time.sleep(0.3)
    exigir("/hola" in srv.salida(), "el servidor dejó de registrar peticiones tras una petición malformada")


# ---------------------------------------------------------------------------
# Hito 4
# ---------------------------------------------------------------------------


def m4_estado(_srv) -> None:
    estado, _, _ = separar(peticion_http("GET", "/hola"))
    exigir(estado.startswith("HTTP/1.1 200"), f"la línea de estado es {estado!r}, esperaba HTTP/1.1 200")


def m4_tipo(_srv) -> None:
    _, cabeceras, _ = separar(peticion_http("GET", "/hola"))
    exigir("content-type" in cabeceras, "falta la cabecera Content-Type")
    exigir("text/html" in cabeceras["content-type"].lower(), "Content-Type no es text/html")


def m4_longitud(_srv) -> None:
    _, cabeceras, cuerpo = separar(peticion_http("GET", "/hola"))
    exigir("content-length" in cabeceras, "falta la cabecera Content-Length")
    try:
        total = int(cabeceras["content-length"])
    except ValueError:
        raise Fallo(f"Content-Length no es un número: {cabeceras['content-length']!r}")
    exigir(
        len(cuerpo) == total,
        f"Content-Length dice {total} pero llegaron {len(cuerpo)} bytes",
    )


def m4_cuerpo(_srv) -> None:
    _, _, cuerpo = separar(peticion_http("GET", "/hola"))
    exigir(b"hola" in cuerpo.lower(), f"el cuerpo no contiene 'Hola' (llegó: {cuerpo[:60]!r})")


# ---------------------------------------------------------------------------
# Hito 5
# ---------------------------------------------------------------------------


def m5_index(_srv) -> None:
    estado, cabeceras, cuerpo = separar(peticion_http("GET", "/"))
    exigir(codigo(estado) == "200", f"GET / devolvió {codigo(estado)}, esperaba 200")
    exigir("text/html" in cabeceras.get("content-type", "").lower(), "GET / no devuelve text/html")
    exigir(b"Servidor de Brian" in cuerpo, "el cuerpo de GET / no es public/index.html")


def m5_css(_srv) -> None:
    estado, cabeceras, cuerpo = separar(peticion_http("GET", "/estilo.css"))
    exigir(codigo(estado) == "200", f"GET /estilo.css devolvió {codigo(estado)}, esperaba 200")
    exigir("text/css" in cabeceras.get("content-type", "").lower(), "el CSS no se sirve como text/css")
    exigir(b"color-scheme" in cuerpo, "el cuerpo no es public/estilo.css")


def m5_404(_srv) -> None:
    estado, _, _ = separar(peticion_http("GET", "/no-existe"))
    exigir(codigo(estado) == "404", f"GET /no-existe devolvió {codigo(estado)}, esperaba 404")


def m5_traversal(_srv) -> None:
    estado, _, cuerpo = separar(peticion_http("GET", "/../README.md"))
    exigir(codigo(estado) != "200", f"GET /../README.md devolvió {codigo(estado)}; no debe servir el README")
    exigir("Curso práctico".encode() not in cuerpo, "el cuerpo contiene el README: hay path traversal")


# ---------------------------------------------------------------------------
# Hito 6
# ---------------------------------------------------------------------------


def m6_saludo(_srv) -> None:
    estado, _, cuerpo = separar(peticion_http("GET", "/saludo"))
    exigir(codigo(estado) == "200", f"GET /saludo devolvió {codigo(estado)}, esperaba 200")
    exigir(b"hola" in cuerpo.lower(), "el cuerpo de /saludo no contiene 'Hola'")


def m6_hora(_srv) -> None:
    estado, cabeceras, cuerpo = separar(peticion_http("GET", "/api/hora"))
    exigir(codigo(estado) == "200", f"GET /api/hora devolvió {codigo(estado)}, esperaba 200")
    exigir("application/json" in cabeceras.get("content-type", "").lower(), "la respuesta no es application/json")
    datos = leer_json(cuerpo)
    exigir(isinstance(datos, dict) and "hora" in datos, "el JSON no tiene la clave 'hora'")


def m6_404(_srv) -> None:
    estado, _, _ = separar(peticion_http("GET", "/nada"))
    exigir(codigo(estado) == "404", f"GET /nada devolvió {codigo(estado)}, esperaba 404")


def m6_405(_srv) -> None:
    estado, _, _ = separar(peticion_http("POST", "/saludo"))
    exigir(codigo(estado) == "405", f"POST /saludo devolvió {codigo(estado)}, esperaba 405")


# ---------------------------------------------------------------------------
# Hito 7
# ---------------------------------------------------------------------------


def m7_eco(_srv) -> None:
    datos = {"nombre": "Brian", "n": 42}
    respuesta = peticion_http(
        "POST",
        "/api/eco",
        cuerpo=json.dumps(datos).encode(),
        cabeceras={"Content-Type": "application/json"},
    )
    estado, cabeceras, cuerpo = separar(respuesta)
    exigir(codigo(estado) == "200", f"POST /api/eco devolvió {codigo(estado)}, esperaba 200")
    exigir("application/json" in cabeceras.get("content-type", "").lower(), "la respuesta no es application/json")
    devuelto = leer_json(cuerpo)
    exigir(devuelto.get("nombre") == "Brian", "el JSON devuelto no conserva 'nombre'")
    exigir(devuelto.get("n") == 42, "el JSON devuelto no conserva 'n'")


def m7_grande(_srv) -> None:
    texto = "x" * 5000
    respuesta = peticion_http(
        "POST",
        "/api/eco",
        cuerpo=json.dumps({"texto": texto}).encode(),
        cabeceras={"Content-Type": "application/json"},
    )
    estado, _, cuerpo = separar(respuesta)
    exigir(codigo(estado) == "200", f"el POST grande devolvió {codigo(estado)}")
    devuelto = leer_json(cuerpo)
    recibido = devuelto.get("texto", "")
    exigir(len(recibido) == 5000, f"el body llegó incompleto: {len(recibido)} de 5000 caracteres")


def m7_malformado(_srv) -> None:
    respuesta = peticion_http(
        "POST",
        "/api/eco",
        cuerpo=b"{no es json}",
        cabeceras={"Content-Type": "application/json"},
    )
    estado, _, _ = separar(respuesta)
    exigir(codigo(estado) == "400", f"un JSON roto devolvió {codigo(estado)}, esperaba 400")


# ---------------------------------------------------------------------------
# Hito 8
# ---------------------------------------------------------------------------


def m8_lento(_srv) -> None:
    inicio = time.monotonic()
    estado, _, _ = separar(peticion_http("GET", "/lento", timeout=4.0))
    transcurrido = time.monotonic() - inicio
    exigir(codigo(estado) == "200", f"GET /lento devolvió {codigo(estado)}")
    exigir(transcurrido >= 0.8, f"/lento respondió en {transcurrido:.2f} s; debería esperar ~1 s")


def m8_concurrente(_srv) -> None:
    resultados: list[object] = []
    barrera = threading.Barrier(2)

    def trabajador() -> None:
        try:
            barrera.wait()
            respuesta = peticion_http("GET", "/lento", timeout=4.0)
            resultados.append(respuesta)
        except Exception as e:  # noqa: BLE001 - se informa en la comprobación
            resultados.append(e)

    hilos = [threading.Thread(target=trabajador, daemon=True) for _ in range(2)]
    inicio = time.monotonic()
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=6)
    total = time.monotonic() - inicio

    exigir(len(resultados) == 2, "una de las dos peticiones concurrentes no terminó")
    for resultado in resultados:
        if isinstance(resultado, Exception):
            raise Fallo(f"una petición concurrente falló: {resultado}")
        estado, _, _ = separar(resultado)
        exigir(codigo(estado) == "200", f"una petición concurrente devolvió {codigo(estado)}")
    exigir(total < 1.8, f"dos /lento tardaron {total:.2f} s; parece que se atienden en serie")


# ---------------------------------------------------------------------------
# Hito 9
# ---------------------------------------------------------------------------


def m9_log(srv: Servidor) -> None:
    peticion_http("GET", "/saludo")
    time.sleep(0.2)
    salida = srv.salida()
    exigir("GET" in salida, "el log no incluye el método")
    exigir("/saludo" in salida, "el log no incluye la ruta")
    exigir("200" in salida, "el log no incluye el código de estado")


def m9_malformada(_srv) -> None:
    peticion(b"BASURA\r\n\r\n", timeout=0.8)
    time.sleep(0.2)
    estado, _, _ = separar(peticion_http("GET", "/hola"))
    exigir(codigo(estado) == "200", "el servidor no respondió tras una petición malformada")


def m9_desconexion(_srv) -> None:
    with socket.create_connection((HOST, PUERTO), timeout=2) as s:
        s.sendall(
            b"POST /api/eco HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{\"a\":"
        )
    time.sleep(0.2)
    estado, _, _ = separar(peticion_http("GET", "/hola"))
    exigir(codigo(estado) == "200", "el servidor no sobrevivió a un cliente que se fue a mitad")


def m9_muda(_srv) -> None:
    with socket.create_connection((HOST, PUERTO), timeout=3) as muda:
        inicio = time.monotonic()
        estado, _, _ = separar(peticion_http("GET", "/hola", timeout=2.0))
        transcurrido = time.monotonic() - inicio
        exigir(codigo(estado) == "200", "no respondió mientras había una conexión muda")
        exigir(transcurrido < 1.5, f"tardó {transcurrido:.2f} s; una conexión muda bloqueó el servidor")


def m9_sigint(srv: Servidor) -> None:
    proc = srv.proc
    assert proc is not None
    os.killpg(os.getpgid(proc.pid), signal.SIGINT)
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        raise Fallo("el servidor no terminó con Ctrl+C en 3 s")


# ---------------------------------------------------------------------------
# Hito 10 (opcional)
# ---------------------------------------------------------------------------


def m10(_srv) -> None:
    ruta = RAIZ / "servidor" / "wsgi.py"
    if not ruta.exists():
        raise Omitido("M10 es opcional: no encuentro servidor/wsgi.py")

    resultado = subprocess.run(
        [sys.executable, "-m", "py_compile", str(ruta)],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        raise Fallo("servidor/wsgi.py no compila")

    sys.path.insert(0, str(RAIZ / "servidor"))
    try:
        spec = importlib.util.spec_from_file_location("wsgi_alumno", ruta)
        assert spec and spec.loader
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
    finally:
        sys.path.pop(0)

    app = getattr(modulo, "app", None) or getattr(modulo, "aplicacion", None)
    exigir(app is not None, "no encuentro app(environ, start_response) en servidor/wsgi.py")

    from wsgiref.util import setup_testing_defaults

    entorno: dict[str, object] = {}
    setup_testing_defaults(entorno)
    entorno.update(
        {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/hola",
            "QUERY_STRING": "",
            "wsgi.input": io.BytesIO(b""),
        }
    )
    capturado: dict[str, object] = {}

    def start_response(estado, cabeceras, exc_info=None):  # noqa: ANN001
        capturado["estado"] = estado
        capturado["cabeceras"] = cabeceras

    salida = app(entorno, start_response)
    cuerpo = b"".join(salida)
    if hasattr(salida, "close"):
        salida.close()

    exigir("200" in str(capturado.get("estado", "")), f"la app WSGI respondió {capturado.get('estado')!r}")
    exigir(b"hola" in cuerpo.lower(), "la app WSGI no devolvió 'Hola'")


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

HITOS: dict[str, tuple[str, list[tuple[str, object]]]] = {
    "m0": (
        "Preparación",
        [
            ("Existe servidor/main.py", m0_existe),
            ("El archivo compila", m0_compila),
            ("La estructura del proyecto está completa", m0_estructura),
        ],
    ),
    "m1": (
        "El socket que escucha",
        [("Lee lo que llega y responde 'hola'", m1)],
    ),
    "m2": (
        "Ver la petición cruda",
        [("Imprime la petición HTTP completa", m2)],
    ),
    "m3": (
        "Parsear la petición",
        [
            ("Separa método, ruta y versión, y los headers", m3_parsea),
            ("Sobrevive a una petición malformada", m3_sobrevive),
        ],
    ),
    "m4": (
        "Primera respuesta HTTP válida",
        [
            ("La línea de estado es HTTP/1.1 200", m4_estado),
            ("Content-Type es text/html", m4_tipo),
            ("Content-Length coincide con el cuerpo", m4_longitud),
            ("El cuerpo contiene 'Hola'", m4_cuerpo),
        ],
    ),
    "m5": (
        "Archivos estáticos",
        [
            ("GET / sirve public/index.html", m5_index),
            ("GET /estilo.css sirve el CSS", m5_css),
            ("GET /no-existe devuelve 404", m5_404),
            ("No hay path traversal", m5_traversal),
        ],
    ),
    "m6": (
        "Router",
        [
            ("GET /saludo responde 200", m6_saludo),
            ("GET /api/hora responde JSON", m6_hora),
            ("GET /nada devuelve 404", m6_404),
            ("POST /saludo devuelve 405", m6_405),
        ],
    ),
    "m7": (
        "POST y JSON",
        [
            ("POST /api/eco devuelve el JSON recibido", m7_eco),
            ("Un body de 5 KB llega completo", m7_grande),
            ("Un JSON roto devuelve 400", m7_malformado),
        ],
    ),
    "m8": (
        "Varias conexiones",
        [
            ("GET /lento tarda ~1 s", m8_lento),
            ("Dos /lento en paralelo tardan ~1 s", m8_concurrente),
        ],
    ),
    "m9": (
        "Robustez",
        [
            ("Registra método, ruta y estado", m9_log),
            ("Sobrevive a una petición malformada", m9_malformada),
            ("Sobrevive a un cliente que se va a mitad", m9_desconexion),
            ("Una conexión muda no lo bloquea", m9_muda),
            ("Termina con Ctrl+C", m9_sigint),
        ],
    ),
    "m10": (
        "Comparar con la realidad (opcional)",
        [("La app WSGI responde 200 en /hola", m10)],
    ),
}


def ejecutar(nombre: str) -> int:
    if nombre not in HITOS:
        print(f"No conozco el hito {nombre!r}. Hitos: {', '.join(HITOS)}")
        return 2

    titulo, comprobaciones = HITOS[nombre]
    print(f"\n{nombre.upper()} · {titulo}\n")

    if nombre == "m10" and not (RAIZ / "servidor" / "wsgi.py").exists():
        print("  ⏭️  La app WSGI responde 200 en /hola")
        print("     → M10 es opcional: no encuentro servidor/wsgi.py")
        print("\n0/1 comprobaciones superadas · 1 omitida")
        return 0

    srv: Servidor | None = None
    fallos = 0
    omitidos = 0
    try:
        if nombre != "m0":
            srv = Servidor()
            try:
                srv.arrancar()
            except Fallo as e:
                print(f"  ❌ No se pudo arrancar el servidor\n     → {e}")
                return 1

        for descripcion, comprobacion in comprobaciones:
            try:
                comprobacion(srv)  # type: ignore[operator]
                print(f"  ✅ {descripcion}")
            except Omitido as e:
                print(f"  ⏭️  {descripcion}\n     → {e}")
                omitidos += 1
            except Fallo as e:
                print(f"  ❌ {descripcion}\n     → {e}")
                fallos += 1
            except Exception as e:  # noqa: BLE001 - el verificador no debe romperse
                print(f"  ❌ {descripcion}\n     → error inesperado del verificador: {e!r}")
                fallos += 1
    finally:
        if srv is not None:
            salida = srv.salida()
            vivo = srv.proc is not None and srv.proc.poll() is None
            srv.cerrar()
            if fallos and salida.strip():
                print("\n--- salida del servidor (últimas líneas) ---")
                for linea in salida.strip().splitlines()[-12:]:
                    print("  " + linea)
            elif fallos and vivo is False and not salida.strip():
                print("\n(el servidor no dejó ninguna salida antes de terminar)")

    total = len(comprobaciones)
    resumen = f"{total - fallos - omitidos}/{total} comprobaciones superadas"
    if omitidos:
        resumen += f" · {omitidos} omitida(s)"
    print(f"\n{resumen}")
    if fallos == 0:
        print("Hito superado. Pásale el relevo al profesor.")
    return 0 if fallos == 0 else 1


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        print("\nHitos: " + ", ".join(HITOS))
        return 2
    codigo_salida = 0
    for nombre in argv[1:]:
        codigo_salida |= ejecutar(nombre.lower())
    return codigo_salida


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
