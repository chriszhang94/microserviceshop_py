import consul
import grpc
import logging
import signal
import sys
import os
import argparse
import environ
import uuid
from concurrent import futures

import requests
from loguru import logger

BASE_DIR = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from user_service.proto import user_pb2_grpc
from user_service.handler.user import UserServicer
from common.grpc_health.v1 import health_pb2, health_pb2_grpc
from common.grpc_health.v1 import health
from common.server import BaseServer
from user_service.settings import setting
USER_SERVICE_HOST = None
USER_SERVICE_PORT = None
CONSUL_HOST = None
CONSUL_PORT = None
SERVICE_ID = "mxshop-user-srv"


def onExit(signo, frame):
    logger.info("Process Terminate")
    sys.exit(0)

def read_config():
    path = environ.Path(__file__) - 1
    env = environ.Env()
    environ.Env.read_env(path('.env'))
    host = env.get_value('user_srv_host')
    port = int(env.get_value('user_srv_port'))
    consul_host = env.get_value('consul_server_host')
    consul_port = int(env.get_value('consul_server_port'))
    return host, port, consul_host, consul_port

def serve():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip',
                        nargs="?",
                        type=str,
                        default=USER_SERVICE_HOST,
                        help="ip")
    parser.add_argument('--port',
                        nargs="?",
                        type=int,
                        default=USER_SERVICE_PORT,
                        help="port")
    args = parser.parse_args()

    logger.add("logs/user_service_{time}.log")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    user_pb2_grpc.add_UserServicer_to_server(UserServicer(), server)
    # 注册健康检查
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    server.add_insecure_port(f'[::]:{args.port}')

    # 主进程退出信号监听
    signal.signal(signal.SIGINT, onExit)
    signal.signal(signal.SIGTERM, onExit)
    logger.info("Start User Srv Service at {}:{}".format(args.ip, args.port))
    server.start()
    server.wait_for_termination()


class UserServiceServer(BaseServer):
    SERVICE_NAME = "user-srv"

    def __init__(self, host, port):
        super(UserServiceServer, self).__init__()
        self.SERVICE_ID = self.SERVICE_NAME + "-" + f'{str(uuid.uuid4())}'
        self.SERVICE_HOST = host
        self.SERVICE_PORT = port
        self.CONSUL_HOST = setting.data["consul"]["host"]
        self.CONSUL_PORT = setting.data["consul"]["port"]
        logger.add("logs/user_service_{time}.log")

    def onExit(self, signo, frame):
        logger.info("User service terminate")
        self.unregister()
        sys.exit(0)

    def read_config_from_env(self):
        path = environ.Path(__file__) - 1
        env = environ.Env()
        environ.Env.read_env(path('.env'))
        self.SERVICE_HOST = env.get_value('user_srv_host')
        if self.SERVICE_PORT is None:
            self.SERVICE_PORT = int(env.get_value('user_srv_port'))
        self.CONSUL_HOST = env.get_value('consul_server_host')
        self.CONSUL_PORT = int(env.get_value('consul_server_port'))

    def register_request(self):
        url = "http://{}:{}/v1/agent/service/register".format(self.CONSUL_HOST, self.CONSUL_PORT)
        headers = {
            "contentType": "application/json"
        }
        rsp = requests.put(url, headers=headers, json={
            "Name": self.SERVICE_NAME,
            "ID": self.SERVICE_ID,
            "Tags": ["mxshop", "bobby", "imooc", "web"],
            "Address": self.SERVICE_HOST,
            "Port": self.SERVICE_PORT,
            "Check": {
                "GRPC": f"{self.SERVICE_HOST}:{self.SERVICE_PORT}",
                "GRPCUseTLS": False,
                "Timeout": "5s",
                "Interval": "5s",
                "DeregisterCriticalServiceAfter": "15s"
            }
        })
        if rsp.status_code == 200:
            print("registered success")
        else:
            print(f"registered failed：{rsp.status_code}")


    def serve(self):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=40))
        user_pb2_grpc.add_UserServicer_to_server(UserServicer(), self.server)
        health_servicer = health.HealthServicer()
        health_pb2_grpc.add_HealthServicer_to_server(health_servicer, self.server)
        self.server.add_insecure_port(f'[::]:{self.SERVICE_PORT}')
        signal.signal(signal.SIGINT, self.onExit)
        signal.signal(signal.SIGTERM, self.onExit)
        logger.info("Start User Srv Service at {}:{}".format(self.SERVICE_HOST, self.SERVICE_PORT))
        self.server.start()
        self.register()
        self.server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig()
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', nargs="?",
                        type=str,
                        default=setting.HOST,
                        help="host")
    parser.add_argument('--port',
                        nargs="?",
                        type=int,
                        default=50052,
                        help="port")
    args = parser.parse_args()
    server = UserServiceServer(args.host, args.port)
    server.serve()
