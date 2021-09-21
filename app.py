from flask import Flask, render_template, send_file, request
from bp import auto_bp
import os

app = Flask(__name__)
app.register_blueprint(auto_bp, url_prefix='/results')

@app.route("/")
def home():
   return render_template("index.html")


@app.route("/adder", methods=["GET", "POST"])
def adder():
 if request.method == "POST":
  url = request.form.get('url')
  f = open('domains.txt','a')
  f.write(url)
  f.write("\n")
  f.close()
  return render_template("index.html", data="Added to queue !")

@app.route("/results")
def results():
   return "Results Here!"

if __name__ == "__main__":
  app.run(port=8000)
