from logging import debug, info, warning, error, basicConfig as logging_conf
from argparse import ArgumentParser
from os import environ, getpid, remove
from os.path import exists
from yaml import safe_load, YAMLError
from requests import post, patch, ConnectionError
from json import dumps, loads
from asyncio import gather, sleep as asleep, run, gather

def app_config(path: str) -> dict:
    try:
        with open(path, 'r') as stream:
                config = safe_load(stream)
                return(config)
    except FileNotFoundError:
        error(f"Configuration file {path} not found")
        exit(1)
    except IOError:
        error(f"Configuration file {path} not accessible")
        exit(1)
    except YAMLError as yamlerr:
        error(f"Error while reading {path}: {yamlerr}")
        exit(1)

def kube_api_token(config: dict) -> str:
    path = config["kubernetes"]["auth_token_path"]
    if not "KUBE_API_TOKEN" in environ:
        try:
            with open(path) as token:
                api_token = token.read()
        except FileNotFoundError:
            error(f"Token {path} not found and KUBE_API_TOKEN environment variable not defined")
            exit(1)
        except IOError:
            error(f"Token file {path} not accessible")
            exit(1)
    else:
        api_token = environ["KUBE_API_TOKEN"]
    return(api_token)

def metrics(config: dict) -> dict:
    req_body = {"query": "{ grid { sessionCount, sessionQueueSize },"
                        "nodesInfo { nodes { id, uri, status, slotCount, sessionCount, stereotypes } } ""}"
                    }
    api_url = f"{config['selenium']['url']}/graphql"
    try:
        resp = post(api_url, data=dumps(req_body))
        if resp.status_code == 200:
            resp_body = resp.json()
            metrics = resp_body["data"]
        else:
            error(f"Unable to retrieve metrics from the grid {resp.status_code}: {resp.json()}")
            exit(1)
        node_metrics = metrics["nodesInfo"]["nodes"]
        load_index_map = {}
        deployments = config["deployments"]
        for d in deployments:
            stereotype_selector = deployments[d]["stereotype_selector"]
            stereotype_value = deployments[d]["stereotype_selector_value"]
            sessions = 0
            slots = 0
            node_count = 0
            node_status = []
            for i in node_metrics:
                if loads(i["stereotypes"])[0]["stereotype"][stereotype_selector] == stereotype_value \
                                                                and i["status"] == "UP":
                        sessions = sessions + int(i["sessionCount"])
                        slots = slots + int(i["slotCount"])
                        node_count = node_count + 1
                        node_status.append({
                            "id": i["id"],
                            "sessionCount": i["sessionCount"]
                        })
            if slots > 0:
                load_index_map.update({
                    d:{
                        "nodeCount": node_count,
                        "loadIndex": sessions/slots,
                        "nodeStatus": node_status
                    }
                })
            else:
                load_index_map.update({
                    d:{
                        "nodeCount": node_count,
                        "loadIndex": 0.0,
                        "nodeStatus": node_status
                    }
                })
        return(load_index_map)
    except ConnectionError as r_err:
        error(f"{api_url} connection error -> {r_err}")
        exit(1)

def drain_node(config: dict, id: str) -> None:
    grid = config['selenium']
    api_url = f"{grid['url']}/se/grid/distributor/node/{id}/drain"
    if "GRID_REGISTRATION_SECRET" in environ:
        secret = environ["GRID_REGISTRATION_SECRET"]
    else:
        secret = ""
    api_headers = {
        "X-REGISTRATION-SECRET": secret
    }
    try:
        resp = post(api_url, headers=api_headers)
        if resp.status_code == 200:
            info(f"Node {id} status was successfully set to draining")
        else:
            warning(f"Unable to drain node {id} with error: {resp.json()}")
    except ConnectionError as r_err:
        error(f"{api_url} connection error -> {r_err}")
        exit(1)

def deployment_scale(config: dict, token: str, api_v: str, deployment: str, \
                                namespace: str, replicas: int) -> None:
    config = config["kubernetes"]
    ca_path = config["ca_cert_path"]
    api_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/strategic-merge-patch+json"
        }
    api_data = {
            "spec": {
                "replicas": replicas
            }
        }
    api_url = f"{config['api_url']}/apis/{api_v}/namespaces/{namespace}/deployments/{deployment}"
    if exists(ca_path):
        try:
            resp = patch(api_url, headers=api_headers, data=dumps(api_data), verify=ca_path)
            if resp.status_code != 200:
                warning(f"Failed to scale deployment {deployment} with error: {resp.json()}")
            else:
                info(f"Deployment {deployment} updated -> replicas count {replicas}")
        except ConnectionError as r_err:
            error(f"{api_url} connection error -> {r_err}")
            exit(1)
    else:
        warning(f"Failed to scale deployment {deployment} with error: {ca_path} not found")

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("-c", "--config", type=str,
                            required=False,
                            default="./config.default.yaml",
                            help="Path to configuration file"
                        )
    parser.add_argument("-p", "--pid-file", type=str,
                            required=False,
                            default="./scaler.pid",
                            help="Path to PID file"
                        )
    parser.add_argument("-l", "--log-level", type=str,
                            required=False,
                            default="info",
                            help="Application logging level"
                        )
    args = parser.parse_args()
    logging_level = args.log_level
    logging_format = "%(asctime)s %(levelname)s %(message)s"
    logging_conf(format = logging_format,
                            level=logging_level.upper(),
                            datefmt="%d-%m-%Y %H:%M:%S"
                    )

    async def upscaler(config: dict, token: str) -> None:
        deployments = config["deployments"]
        info("Starting upscaler")
        while True:
            load_map = metrics(config)
            for target in load_map:
                api_v = deployments[target]["api_version"]
                namespace = deployments[target]["namespace"]
                if deployments[target]["scale_up_threshold"] > 1.0:
                    threshold = 1.0
                else:
                    threshold = deployments[target]["scale_up_threshold"]
                if load_map[target]["loadIndex"] >= threshold and \
                                load_map[target]["nodeCount"] < deployments[target]["max_replicas"]:
                    replicas = load_map[target]["nodeCount"] + deployments[target]["scale_up_step"]
                    deployment_scale(config, token, api_v, target, namespace, replicas)
                else:
                    debug(f"Deployment {target} does not need to scale up")
            await asleep(config["scaler"]["scale_up_interval"])

    async def downscaler(config: dict, token: str) -> None:
        deployments = config["deployments"]
        info("Starting downscaler")
        while True:
            load_map = metrics(config)
            for target in load_map:
                api_v = deployments[target]["api_version"]
                namespace = deployments[target]["namespace"]
                if deployments[target]["scale_down_threshold"] < 0.0:
                    threshold = 0.0
                else:
                    threshold = deployments[target]["scale_down_threshold"]
                if load_map[target]["loadIndex"] < threshold and \
                                load_map[target]["nodeCount"] > deployments[target]["min_replicas"]:
                    drain_queue = filter(lambda x: x["sessionCount"] == 0, load_map[target]["nodeStatus"])
                    replicas = load_map[target]["nodeCount"]
                    for node in drain_queue:
                        if replicas > deployments[target]["min_replicas"]:
                            replicas = replicas - deployments[target]["scale_down_step"]
                            drain_node(config, node["id"])
                            deployment_scale(config, token, api_v, target, namespace, replicas)
                else:
                    debug(f"Deployment {target} does not need to scale down")
            await asleep(config["scaler"]["scale_down_interval"])

    async def write_pid(path: str) -> None:
        await asleep(15)
        with open(path, "w") as f:
            f.write(str(getpid()))

    async def main() -> None:
        config = app_config(args.config)
        token = kube_api_token(config)
        await gather(upscaler(config, token), downscaler(config, token), write_pid(args.pid_file))

    try:
        run(main())
    except KeyboardInterrupt:
        try:
            remove(args.pid_file)
        except FileNotFoundError:
            pass
        info("Interrupted -> Exit")
        exit(130)
