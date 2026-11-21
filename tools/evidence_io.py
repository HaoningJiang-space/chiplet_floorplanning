"""JSON encodings used by the frozen experiment files and ATPlace inputs."""
import json


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False, separators=(',', ':'))+'\n', encoding='utf8')


def write_pretty_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf8", newline="\n")
