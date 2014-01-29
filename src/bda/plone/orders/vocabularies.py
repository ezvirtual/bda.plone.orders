from bda.plone.orders.common import get_all_vendors
from bda.plone.orders.common import get_allowed_vendors
from bda.plone.orders.common import get_allowed_orders_uid
from bda.plone.orders.common import get_order
from plone.uuid.interfaces import IUUID
from zope.component.hooks import getSite

import plone.api


def all_vendors_vocab():
    """Vocabulary for all vendor areas by uuid.
    """
    all_vendors = get_all_vendors()
    vocab = [(IUUID(it),
             '{0} ({1})'.format(it.Title(), it.absolute_url_path()))
             for it in all_vendors]
    return vocab


def allowed_vendors_vocab(user=None):
    """Vocabulary for allowed vendors.
    """
    allowed_vendors = get_allowed_vendors(user=user)
    vocab = [(IUUID(it),
             '{0} ({1})'.format(it.Title(), it.absolute_url_path()))
             for it in allowed_vendors]
    return vocab


def allowed_customers_vocab(user=None):
    allowed_orders = get_allowed_orders_uid(user=user)
    context = getSite()
    res = set(get_order(context, it).attrs['creator'] for it in allowed_orders)
    vocab = []
    for it in res:
        customer = plone.api.user.get(userid=it)
        if customer:
            # soft dep on bda.plone.shop
            first = customer.getProperty('firstname', '')
            last = customer.getProperty('lastname', '')
            # fallback
            full = customer.getProperty('fullname', '')

            name = (first or last) and '{0}, {1}'.format(first, last) or full
        else:
            name = it
        title = name and '{0} ({1})'.format(it, name) or it
        vocab.append((it, title))
    return vocab
