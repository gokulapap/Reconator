#python run.py {domain}

import os
import sys
import telebot
from time import sleep

url = sys.argv[1]
bot = telebot.TeleBot(os.environ['API_KEY'])
chat_id = os.environ['CHAT_ID']

os.system("touch results/{}-output.txt".format(url))
os.system("chmod 777 /app/* -R")

bot.send_message(chat_id, f"Recon started for {url} !")
bot.send_message(chat_id, "[+] If you're not getting the notification on finish, Try restarting dynos\n[+] The Scan time may take longer for larger targets")

#0_index_of_results
os.system(f"bash modules/index.sh {url}")

#1_dnscan
os.system(f"bash modules/dnscan.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#2_clickjacking
os.system(f"python modules/clickjacking {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#3_corstest
os.system(f"python modules/corstest {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#4_firwall_detection
os.system(f"bash modules/firewall.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#5_davtest
os.system(f"bash modules/davtest.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#6_robots_check
os.system(f"bash modules/robots.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#7_subdomain_enumeration
os.system(f"bash modules/subdomains.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#8_dirbrute
os.system(f"bash modules/dirb.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#9_js+link_finder
os.system(f"bash modules/js-finder.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#10_subdomain_takeover
os.system(f"bash modules/subtake.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#11_subdomains_title_cname
os.system(f"bash modules/sub_title_cname.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#12_subdomains_ip_server
os.system(f"bash modules/sub_ip_server.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#13_whois_lookup
os.system(f"bash modules/whois.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#14_shcheck
os.system(f"bash modules/shcheck.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#15_wappalyzer_cli
os.system(f"bash modules/wappy.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#16_urls_gather
os.system(f"bash modules/gather_urls.sh {url}")
os.system('python insert.py {}'.format(url))

sleep(4)

#17_seperating_with_gf_patterns
os.system(f"bash modules/gf_patterns.sh {url}")
os.system('python insert.py {}'.format(url))

###########################################################

bot.send_message(chat_id, f"Recon for {url} is completed ! you can check the results now on website at path /scanned !")
#dumping to database with insert.py
os.system('python insert.py {} last'.format(url))
