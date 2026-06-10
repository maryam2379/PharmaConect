from flask import Flask,render_template,request,redirect,url_for
from werkzeug.security import generate_password_hash

app=Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")

if __name__=="__main__":
    app.run(debug=True)