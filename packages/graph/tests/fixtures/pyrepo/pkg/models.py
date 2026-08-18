class User:
    def save(self):
        return True

    @property
    def label(self):
        return "u"


def helper():
    def inner():
        return 1
    return inner
