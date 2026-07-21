# ad-recharge

## Install

```shell
cd ad-recharge

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip

pip install playwright
python -m playwright install chromium
```

## Uninstall

```shell
python -m playwright uninstall --all
rm -rf ~/.cache/ms-playwright
```

## Start

Start in headed mode and log in. An interval of 0 means the script waits indefinitely after the current cycle, so it does not reload again automatically.

```shell
python ad-recharge.py --interval 0 --headed
```

Stop the script, then restart it in headless mode.

```shell
python ad-recharge.py --interval 60
```
