import concurrent.futures
import requests
import threading
import sys
import time
import bs4
from colorama import Fore, Style
inputfile=sys.argv[1]
with open(inputfile, "r") as f:
	inputurl = [line.rstrip() for line in f]
threadLocal = threading.local()
count = len(inputurl)
def get_session():
    if not hasattr(threadLocal, "session"):
        threadLocal.session = requests.Session()
    return threadLocal.session
def check_url(url):
	try :
		session=get_session()
		res=session.get(url, timeout=1)
		html=bs4.BeautifulSoup(res.text, "lxml")
		t=html.title
		print(Style.BRIGHT + Fore.WHITE + (url) + " : " + Fore.YELLOW + (t.text))
	except:
		pass
def itterate_urls(inputurl):
	url=str(inputurl)
	check_url(url)
if __name__ == "__main__":
	start_time = time.time()
	with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
       		executor.map(itterate_urls, inputurl)
	duration = time.time() - start_time

