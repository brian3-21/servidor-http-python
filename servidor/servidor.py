import socket 
import time

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

s.bind(("127.0.0.1", 8080))

s.listen()


while True:
    print("Waiting for clients")
    conn, addr = s.accept()

    

    time.sleep(1)

