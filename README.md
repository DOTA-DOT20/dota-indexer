#  Install mysql
Here I use docker to install the latest version
# clone project
```
git clone https://github.com/octavei/dota-indexer.git
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
Note that the configuration in the .env file should be modified according to your actual situation.

# run
```angular2html
python indexer.py
```


