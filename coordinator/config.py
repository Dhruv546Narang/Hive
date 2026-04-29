import os
import tomllib
from pydantic import BaseModel


class HiveConfig(BaseModel):
    cluster_secret: str = "hive-secret-123"
    model_dir: str = os.path.expanduser("~/hive/models")
    coordinator_port: int = 8000
    worker_port: int = 50052      # llama.cpp rpc-server port
    inference_port: int = 8081    # distributed llama-server API port
    offload_factor: float = 0.6


def load_config() -> HiveConfig:
    """Load config from ~/.hive/config.toml, fall back to bundled default."""
    home_dir = os.path.expanduser("~")
    user_config_path = os.path.join(home_dir, ".hive", "config.toml")
    local_config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "config", "default.toml"
    )

    config_path = (
        user_config_path
        if os.path.exists(user_config_path)
        else local_config_path
    )

    if os.path.exists(config_path):
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
            return HiveConfig(**data)
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")

    return HiveConfig()


settings = load_config()
