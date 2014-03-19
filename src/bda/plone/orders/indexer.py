from zope.interface import Interface
from plone.indexer import indexer
from .interfaces import IBuyable


@indexer(Interface)
def customer_role(obj):
    # read users and groups having customer role directly on context, not
    # inherited! groups gets prefixed with ``group:``
    # XXX
    return []