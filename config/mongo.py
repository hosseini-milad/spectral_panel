from mongoengine import connect


def connect_mongodb():
    """
    Connect to the existing SIEM MongoDB database.

    Source collections are read-only inputs. Derived collections are written
    by explicit pipeline commands.
    """

    return connect(
        db="siem_db",
        host="localhost",
        port=27017,
        alias="default",
    )
