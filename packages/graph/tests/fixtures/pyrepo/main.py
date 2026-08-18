from pkg.models import User, helper as h
import pkg.models


def run():
    u = User()
    u.save()
    h()
    pkg.models.helper()
