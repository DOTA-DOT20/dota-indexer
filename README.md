# Video Tutorial
[![asciicast](https://asciinema.org/a/HNjOsxkvpNGFF4yGZhM9DseEr.svg)](https://asciinema.org/a/HNjOsxkvpNGFF4yGZhM9DseEr)

# OS
Linux(Ubuntu 20.04/22.04) or MacOS
> Other operating systems can also be used, but are not recommended.


# python
python 3.10 or above

# install rust environment (only for Windows)
```angular2html
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
rustc --version
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

# pip install
```angular2html
cd dota-indexer
pip install -r requirements.txt
```
# Modify modify environment variables as below

```angular2html
cp .env.example .env
nano .env

# mysql
HOST="localhost"
MYSQLUSER="dota"
PASSWORD="Dota$2024"
DATABASE="dota"

# The name of the connected network: Polkadot mainnet is Polkadot and testnet is Development
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
START_BLOCK=700000
# How many blocks to delay the final block
DELAY_BLOCK=3

```



> Note that the configuration in the .env file should be modified according to your actual situation.

# run
```angular2html
python indexer.py
```


