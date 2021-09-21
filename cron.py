from time import sleep
import os

#checks the domains.txt every 60 secs
while True:
  a = open('domains.txt', 'r')
  b = a.readlines()
  a.close()
  if len(b) == 0:
    pass
  else:
    url = b[0]
    b.pop(0)
    f = open('domains.txt', 'w')
    for i in b:
      f.write(i)
    f.close()

    #sends to run.py
    os.system('python run.py {}'.format(url))
    #30 minutes sleep for scan to be finished
    sleep(1740)

  sleep(60)
