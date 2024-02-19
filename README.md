# OS
linux or MacOS
> Other operating systems can also be used, but are not recommended.
# python
python3.11.6


# install rust environment
```angular2html
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
rustc --version

```

#  Install mysql
Here I use docker to install the latest version
# clone project
```
git clone  https://github.com/DOTA-DOT20/dota-indexer.git 
```
# Create a python virtual environment and activate it
```angular2html
python3 -m venv myenv
source myenv/bin/activate
```
# pip install
```angular2html
pip install -r requirements.txt
```
# Modify modify environment variables

```angular2html
cp .env.example .env
```
> Note that the configuration in the .env file should be modified according to your actual situation.

# run
```angular2html
python indexer.py
```


