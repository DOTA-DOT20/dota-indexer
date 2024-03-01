# Video Tutorial
[![asciicast](https://asciinema.org/a/HNjOsxkvpNGFF4yGZhM9DseEr.svg)](https://asciinema.org/a/HNjOsxkvpNGFF4yGZhM9DseEr)

# OS
Linux(Ubuntu 20.04/22.04) or MacOS
> Other operating systems might be used smoothly, but not recommended.


# Install python
python 3.10 or above

# Install Rust environment (only for Windows)
```angular2html
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
rustc --version
```
# OpenSSL
```angular2html
sudo apt install libssl-dev libssl libcrypto
```
# Install and setup mysql
```
sudo apt update
sudo apt install mysql-server
```

# Create user and database

```
sudo mysql

CREATE USER 'dota'@'localhost' IDENTIFIED BY 'Dota$2024';
GRANT ALL PRIVILEGES ON *.* TO 'dota'@'localhost';
FLUSH PRIVILEGES;
CREATE DATABASE dota;

exit
```

# Clone indexer
```
git clone https://github.com/DOTA-DOT20/dota-indexer.git 
```

# Create a python virtual environment and activate it
```angular2html
python3 -m venv myenv
source myenv/bin/activate
```

# Install the indexer
```angular2html
cd dota-indexer
pip install -r requirements.txt
```
# Modify environment variables as below

```angular2html
cp .env.example .env
nano .env

# mysql
HOST="localhost"
MYSQLUSER="dota"
PASSWORD="Dota$2024"
DATABASE="dota"

# The name of the connected network: Polkadot mainnet should be "Polkadot" while testnet should be "Development"
CHAIN="Development"
URL="wss://rect.me"

# log configuration
# How many days to make a backup
ROTATION=1
#Maximum number of weeks of data to retain
RENTENTION=4

# Block to start indexing
# START_BLOCK should be the same across the entire network and is part of the consensus.
# When the indexer is first started, it should be near the latest block of the network.
START_BLOCK=719300

# How many blocks to delay the final block
DELAY_BLOCK=3


Press Ctrl+x / y / Enter to quit the editor
```



> Note that the configuration in the .env file should be modified according to your actual situation.

# Run the indexer
```angular2html
python indexer.py

You could use screen or nohup & to run the indexer on the background
```

# Connect to your database
```
mysql -u dota -p dota

Host: 127.0.0.1
user: dota
password: Dota$2024
database: dota
```

# Windows部署方式中文版（非常详细）
```
[WIN系统部署方式](https://ln2qk4x82d.k.topthink.com/@rmwnjw2qgg/anzhuangsuoxuruanjian.html)
```

# How to test the indexer
```
Send transactions according to the rules of dot20 standard

[DOT20 - The Fungible Inscription standard](https://docs.dota.fyi/dot20)
[DOT20 - 波卡同质铭文协议](https://docs.dota.fyi/dot20cn)
```
