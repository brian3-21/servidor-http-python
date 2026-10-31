import socket

HOST = "0.0.0.0"
PORT = 8000

# 1. Crear el socket TCP
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

# 2. Asociar a IP y puerto
server_socket.bind((HOST, PORT))

# 3. Poner a escuchar
server_socket.listen(5)
print(f"Servidor HTTP escuchando en http://{HOST}:{PORT}")

while True:
    # 4. Aceptar una conexión (bloquea hasta que llega un cliente)
    client_socket, client_address = server_socket.accept()
    print(f"Conexión de import socket

HOST = "0.0.0.0"
PORT = 8000

# 1. Crear el socket TCP
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

# 2. Asociar a IP y puerto
server_socket.bind((HOST, PORT))

# 3. Poner a escuchar
server_socket.listen(5)
print(f"Servidor HTTP escuchando en http://{HOST}:{PORT}")

while True:
    # 4. Aceptar una conexión (bloquea hasta que llega un cliente)
    client_socket, client_address = server_socket.accept()
    print(f"Conexión de {client_address}")

    # 5. Leer la petición (hasta 1024 bytes)
    request = client_socket.recv(1024).decode("utf-8", errors="ignore")
    print("--- Petición recibida ---")
    print(request)

    # 6. Construir la respuesta HTTP
    body = "<html><body><h1>Hola desde mi servidor HTTP</h1></body></html>"
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body.encode('utf-8'))}\r\n"
        "Connection: close\r\n"
        "\r\n"
        f"{body}"
    )

    # 7. Enviar y cerrar
    client_socket.sendall(response.encode("utf-8"))
    client_socket.close(){client_address}")

    # 5. Leer la petición (hasta 1024 bytes)
    request = client_socket.recv(1024).decode("utf-8", errors="ignore")
    print("--- Petición recibida ---")
    print(request)

    # 6. Construir la respuesta HTTP
    body = "<html><body><h1>Hola desde mi servidor HTTP</h1></body></html>"
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body.encode('utf-8'))}\r\n"
        "Connection: close\r\n"
        "\r\n"
        f"{body}"
    )

    # 7. Enviar y cerrar
    client_socket.sendall(response.encode("utf-8"))
    client_socket.close()