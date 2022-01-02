
# python retrive.py {url}

import os
import psycopg2
import base64
import sys

url = sys.argv[1]
DATABASE_URL = os.environ['DATABASE_URL']

conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()

cur.execute(f"select result from output where domain = '{url}'")
t = cur.fetchall()

res = t[0][0]
final = base64.standard_b64decode(res)
final = final.decode('utf-8')
f = open('/app/results/{}-output.txt'.format(url), 'w')
f.write(final)
f.close()

conn.commit()

cur.execute(f"select gau from output where domain = '{url}'")
t = cur.fetchall()

res = t[0][0]
final = base64.standard_b64decode(res)
final = final.decode('utf-8')
f = open('/app/results/{}-gau.txt'.format(url), 'w')
f.write(final)
f.close()

cur.close()
conn.close()
