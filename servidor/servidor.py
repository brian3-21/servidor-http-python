import socket 

local = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
local.bind(("127.0.0.1", 8080))
local.listen()   

print(local)