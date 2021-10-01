from flask import Flask, render_template, send_file, request
from bp import auto_bp
import os
import psycopg2

app = Flask(__name__)
app.register_blueprint(auto_bp, url_prefix='/results')

@app.route("/")
def home():
   return render_template("index.html")


@app.route("/adder", methods=["GET", "POST"])
def adder():
 if request.method == "POST":
  url = request.form.get('url')
  DATABASE_URL = os.environ['DATABASE_URL']

  conn = psycopg2.connect(DATABASE_URL, sslmode='require')
  cur = conn.cursor()

  cur.execute(f"insert into queue ('target',) values ('{url}')")
  conn.commit()

  cur.close()
  conn.close()

  return render_template("index.html", data="Added to queue !")

@app.route("/results")
def results():
   return "Results Here!"

if __name__ == "__main__":
  app.run(port=8000)
