# bp.py
from flask import Blueprint
from flask_autoindex import AutoIndexBlueprint

auto_bp = Blueprint('auto_bp', __name__)
AutoIndexBlueprint(auto_bp, browse_root='/root/dev/reconator/results')
