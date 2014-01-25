from Acquisition import aq_parent
from Products.CMFPlone.interfaces import IPloneSiteRoot
from bda.plone.cart import extractitems
from bda.plone.cart import get_catalog_brain
from bda.plone.cart import get_data_provider
from bda.plone.cart import get_item_data_provider
from bda.plone.cart import get_item_state
from bda.plone.cart import get_item_stock
from bda.plone.cart import get_object_by_uid
from bda.plone.cart import readcookie
from bda.plone.checkout import CheckoutAdapter
from bda.plone.checkout import CheckoutError
from bda.plone.payment.interfaces import IPaymentData
from bda.plone.shipping import Shippings
from bda.plone.shop.interfaces import IBuyable
from decimal import Decimal
from node.ext.zodb import OOBTNode
from node.utils import instance_property
from plone.uuid.interfaces import IUUID
from repoze.catalog.catalog import Catalog
from repoze.catalog.indexes.field import CatalogFieldIndex
from repoze.catalog.indexes.keyword import CatalogKeywordIndex
from repoze.catalog.indexes.text import CatalogTextIndex
from repoze.catalog.query import Any
from repoze.catalog.query import Eq
from souper.interfaces import ICatalogFactory
from souper.soup import NodeAttributeIndexer
from souper.soup import NodeTextIndexer
from souper.soup import Record
from souper.soup import get_soup
from zope.component import adapter
from zope.component.interfaces import ISite
from zope.interface import implementer

from .interfaces import IVendor

import datetime
import plone.api as ploneapi
import time
import uuid


DT_FORMAT = '%d.%m.%Y %H:%M'

# static uuid for the PortalRoot, as it doesn't have a uuid by default
UUID_PLONE_ROOT = '77c4390d-1179-44ba-9d57-46d23ac292c6'


@implementer(IUUID)
@adapter(IPloneSiteRoot)
def plone_root_uuid(context):
    return UUID_PLONE_ROOT


def create_ordernumber():
    onum = hash(time.time())
    if onum < 0:
        return '0%s' % str(abs(onum))
    return '1%s' % str(onum)


def get_order(context, uid):
    if not isinstance(uid, uuid.UUID):
        uid = uuid.UUID(uid)
    soup = get_soup('bda_plone_orders_orders', context)
    return [_ for _ in soup.query(Eq('uid', uid))][0]


def get_vendor(context):
    """Returns the (nearest) vendor or the main shop by traversing up the
    content tree.
    """
    if IVendor.providedBy(context) or ISite.providedBy(context):
        return context
    else:
        parent = aq_parent(context)
        if parent == context:
            return context
        else:
            return get_vendor(parent)


def get_all_vendors():
    cat = ploneapi.portal.get_tool('portal_catalog')
    query = {}
    query['object_provides'] = IVendor.__identifier__
    res = cat.searchResults(query)
    res = [it.getObject() for it in res]
    root = ploneapi.portal.get()
    if not IVendor.providedBy(root):
        res.append(root)
    return res


def get_vendor_areas(user=None):
    if not user:
        user = ploneapi.user.get_current()
    all_vendors = get_all_vendors()
    try:
        vendor_shops = [
            vendor for vendor in all_vendors
                if ploneapi.user.get_permissions(user=user, obj=vendor).get(
                    'bda.plone.orders: Vendor Orders')
        ]
    except ploneapi.exc.UserNotFoundError:
        # might be Zope root user
        return []
    return vendor_shops


def get_allowed_orders(context, user=None):
    """Get all orders from bookings related to a shop, as the shop_uid is only
    indexed on bda_plone_orders_bookings soup and not on
    bda_plone_orders_orders.

    If you had a previous version of bda.plone.shop without mutli client
    feature installed, please run the bda.plone.orders "Add shop_uid to booking
    records" upgrade step.

    >>> [it[1].attrs['shop_uid'] for it in soup.data.items()]
    >>> [it.attrs['order_uid'] for it in soup.query(Eq('creator', 'test'))]

    """
    manageable_shops = get_vendor_areas(user)
    query = Any('shop_uid', [IUUID(it) for it in manageable_shops])
    soup = get_soup('bda_plone_orders_bookings', context)
    res = soup.query(query)
    order_uids = [it.attrs['order_uid'] for it in res]
    # TODO: make a set of order_uids
    return order_uids


@implementer(ICatalogFactory)
class BookingsCatalogFactory(object):

    def __call__(self, context=None):
        catalog = Catalog()
        uid_indexer = NodeAttributeIndexer('uid')
        catalog[u'uid'] = CatalogFieldIndex(uid_indexer)
        buyable_uid_indexer = NodeAttributeIndexer('buyable_uid')
        catalog[u'buyable_uid'] = CatalogFieldIndex(buyable_uid_indexer)
        order_uid_indexer = NodeAttributeIndexer('order_uid')
        catalog[u'order_uid'] = CatalogFieldIndex(order_uid_indexer)
        shop_uid_indexer = NodeAttributeIndexer('shop_uid')
        catalog[u'shop_uid'] = CatalogFieldIndex(shop_uid_indexer)
        creator_indexer = NodeAttributeIndexer('creator')
        catalog[u'creator'] = CatalogFieldIndex(creator_indexer)
        created_indexer = NodeAttributeIndexer('created')
        catalog[u'created'] = CatalogFieldIndex(created_indexer)
        exported_indexer = NodeAttributeIndexer('exported')
        catalog[u'exported'] = CatalogFieldIndex(exported_indexer)
        title_indexer = NodeAttributeIndexer('title')
        catalog[u'title'] = CatalogFieldIndex(title_indexer)
        return catalog


@implementer(ICatalogFactory)
class OrdersCatalogFactory(object):

    def __call__(self, context=None):
        catalog = Catalog()
        uid_indexer = NodeAttributeIndexer('uid')
        catalog[u'uid'] = CatalogFieldIndex(uid_indexer)
        ordernumber_indexer = NodeAttributeIndexer('ordernumber')
        catalog[u'ordernumber'] = CatalogFieldIndex(ordernumber_indexer)
        booking_uids_indexer = NodeAttributeIndexer('booking_uids')
        catalog[u'booking_uids'] = CatalogKeywordIndex(booking_uids_indexer)
        creator_indexer = NodeAttributeIndexer('creator')
        catalog[u'creator'] = CatalogFieldIndex(creator_indexer)
        created_indexer = NodeAttributeIndexer('created')
        catalog[u'created'] = CatalogFieldIndex(created_indexer)
        state_indexer = NodeAttributeIndexer('state')
        catalog[u'state'] = CatalogFieldIndex(state_indexer)
        salaried_indexer = NodeAttributeIndexer('salaried')
        catalog[u'salaried'] = CatalogFieldIndex(salaried_indexer)
        firstname_indexer = NodeAttributeIndexer('personal_data.firstname')
        catalog[u'personal_data.firstname'] = CatalogFieldIndex(
            firstname_indexer
        )
        lastname_indexer = NodeAttributeIndexer('personal_data.lastname')
        catalog[u'personal_data.lastname'] = CatalogFieldIndex(
            lastname_indexer
        )
        city_indexer = NodeAttributeIndexer('billing_address.city')
        catalog[u'billing_address.city'] = CatalogFieldIndex(city_indexer)
        search_attributes = ['personal_data.lastname',
                             'personal_data.firstname',
                             'billing_address.city',
                             'ordernumber']
        text_indexer = NodeTextIndexer(search_attributes)
        catalog[u'text'] = CatalogTextIndex(text_indexer)
        return catalog


SKIP_PAYMENT_IF_RESERVED = True


class OrderCheckoutAdapter(CheckoutAdapter):

    @instance_property
    def order(self):
        return Record()

    @property
    def vessel(self):
        return self.order.attrs

    @property
    def skip_payment(self):
        return SKIP_PAYMENT_IF_RESERVED \
            and self.order.attrs['state'] == 'reserved'

    @property
    def skip_payment_redirect_url(self):
        return '%s/@@reservation_done?uid=%s' % (self.context.absolute_url(),
                                                 self.order.attrs['uid'])

    @property
    def items(self):
        return extractitems(readcookie(self.request))

    def ordernumber_exists(self, soup, ordernumber):
        for order in soup.query(Eq('ordernumber', ordernumber)):
            return bool(order)
        return False

    def save(self, providers, widget, data):
        super(OrderCheckoutAdapter, self).save(providers, widget, data)
        creator = None
        member = self.context.portal_membership.getAuthenticatedMember()
        if member:
            creator = member.getId()
        created = datetime.datetime.now()
        order = self.order
        sid = data.fetch('checkout.shipping_selection.shipping').extracted
        shipping = Shippings(self.context).get(sid)
        order.attrs['shipping'] = shipping.calculate(self.items)
        uid = order.attrs['uid'] = uuid.uuid4()
        order.attrs['creator'] = creator
        order.attrs['created'] = created
        order.attrs['salaried'] = 'no'
        bookings = self.create_bookings(order)
        booking_uids = list()
        all_available = True
        for booking in bookings:
            booking_uids.append(booking.attrs['uid'])
            if booking.attrs['remaining_stock_available'] is not None\
                    and booking.attrs['remaining_stock_available'] < 0:
                all_available = False
        order.attrs['booking_uids'] = booking_uids
        order.attrs['state'] = all_available and 'new' or 'reserved'
        orders_soup = get_soup('bda_plone_orders_orders', self.context)
        ordernumber = create_ordernumber()
        while self.ordernumber_exists(orders_soup, ordernumber):
            ordernumber = create_ordernumber()
        order.attrs['ordernumber'] = ordernumber
        orders_soup.add(order)
        bookings_soup = get_soup('bda_plone_orders_bookings', self.context)
        for booking in bookings:
            bookings_soup.add(booking)
        return uid

    def create_bookings(self, order):
        ret = list()
        cart_data = get_data_provider(self.context)
        currency = cart_data.currency
        shop = get_vendor(self.context)
        shop_uid = uuid.UUID(IUUID(shop))
        items = self.items
        for uid, count, comment in items:
            brain = get_catalog_brain(self.context, uid)
            obj = brain.getObject()
            item_state = get_item_state(obj, self.request)
            if not item_state.validate_count(item_state.aggregated_count):
                raise CheckoutError(u'Item no longer available')
            item_stock = get_item_stock(obj)
            if item_stock.available is not None:
                item_stock.available -= float(count)
            item_data = get_item_data_provider(obj)
            booking = OOBTNode()
            booking.attrs['uid'] = uuid.uuid4()
            booking.attrs['buyable_uid'] = uid
            booking.attrs['buyable_count'] = count
            booking.attrs['buyable_comment'] = comment
            booking.attrs['order_uid'] = order.attrs['uid']
            booking.attrs['shop_uid'] = shop_uid
            booking.attrs['creator'] = order.attrs['creator']
            booking.attrs['created'] = order.attrs['created']
            booking.attrs['exported'] = False
            booking.attrs['title'] = brain and brain.Title or 'unknown'
            booking.attrs['net'] = item_data.net
            booking.attrs['vat'] = item_data.vat
            booking.attrs['currency'] = currency
            booking.attrs['quantity_unit'] = item_data.quantity_unit
            booking.attrs['remaining_stock_available'] = item_stock.available
            ret.append(booking)
        return ret


class OrderData(object):

    def __init__(self, context, uid=None, order=None):
        assert(uid and not order or order and not uid)
        self.context = context
        if uid and not isinstance(uid, uuid.UUID):
            uid = uuid.UUID(uid)
        self._uid = uid
        self._order = order

    @property
    def uid(self):
        if self._uid:
            return self._uid
        return self.order.attrs['uid']

    @property
    def order(self):
        if self._order:
            return self._order
        return get_order(self.context, self.uid)

    @property
    def bookings(self):
        soup = get_soup('bda_plone_orders_bookings', self.context)
        return soup.query(Eq('order_uid', self.uid))

    @property
    def net(self):
        ret = 0.0
        for booking in self.bookings:
            count = float(booking.attrs['buyable_count'])
            ret += booking.attrs.get('net', 0.0) * count
        return ret

    @property
    def vat(self):
        ret = 0.0
        for booking in self.bookings:
            count = float(booking.attrs['buyable_count'])
            net = booking.attrs.get('net', 0.0) * count
            ret += net * booking.attrs.get('vat', 0.0) / 100
        return ret

    @property
    def shipping(self):
        return float(self.order.attrs['shipping'])

    @property
    def total(self):
        ret = 0.0
        for booking in self.bookings:
            count = float(booking.attrs['buyable_count'])
            net = booking.attrs.get('net', 0.0) * count
            ret += net
            ret += net * booking.attrs.get('vat', 0.0) / 100
        return ret + self.shipping

    def increase_stock(self, bookings):
        for booking in bookings:
            obj = get_object_by_uid(self.context, booking.attrs['buyable_uid'])
            # object no longer exists
            if not obj:
                continue
            stock = get_item_stock(obj)
            stock.available += float(booking.attrs['buyable_count'])

    def decrease_stock(self, bookings):
        for booking in bookings:
            obj = get_object_by_uid(self.context, booking.attrs['buyable_uid'])
            # object no longer exists
            if not obj:
                continue
            stock = get_item_stock(obj)
            stock.available -= float(booking.attrs['buyable_count'])


class BuyableData(object):

    def __init__(self, context):
        assert IBuyable.providedBy(context)
        self.context = context

    def item_ordered(self, state=[]):
        """Return total count buyable item was ordered.
        """
        context = self.context
        bookings_soup = get_soup('bda_plone_orders_bookings', context)
        order_bookings = dict()
        for booking in bookings_soup.query(Eq('buyable_uid', context.UID())):
            # TODO: BUG? why is bookings only scoped in this block and not used
            # elsewhere?
            bookings = order_bookings.setdefault(
                booking.attrs['order_uid'], list())
            bookings.append(booking)
        orders_soup = get_soup('bda_plone_orders_orders', context)
        count = Decimal('0')
        for order_uid, bookings in order_bookings.items():
            order = [_ for _ in orders_soup.query(Eq('uid', order_uid))][0]
            if not state:
                for booking in bookings:
                    count += booking.attrs['buyable_count']
            else:
                if order.attrs['state'] in state:
                    for booking in bookings:
                        count += booking.attrs['buyable_count']
        return count


@implementer(IPaymentData)
class PaymentData(object):

    def __init__(self, context):
        self.context = context

    @instance_property
    def order_data(self):
        return OrderData(self.context, uid=self.order_uid)

    @property
    def amount(self):
        amount = '%0.2f' % self.order_data.total
        amount = amount[:amount.index('.')] + amount[amount.index('.') + 1:]
        return amount

    @property
    def currency(self):
        return get_data_provider(self.context).currency

    @property
    def description(self):
        order = self.order_data.order
        attrs = order.attrs
        amount = '%s %s' % (self.currency,
                            str(round(self.order_data.total, 2)))
        description = ', '.join([
            attrs['created'].strftime(DT_FORMAT),
            attrs['personal_data.firstname'],
            attrs['personal_data.lastname'],
            attrs['billing_address.city'],
            amount])
        return description

    @property
    def ordernumber(self):
        return self.order_data.order.attrs['ordernumber']

    def uid_for(self, ordernumber):
        soup = get_soup('bda_plone_orders_orders', self.context)
        for order in soup.query(Eq('ordernumber', ordernumber)):
            return str(order.attrs['uid'])

    def data(self, order_uid):
        self.order_uid = order_uid
        return {
            'amount': self.amount,
            'currency': self.currency,
            'description': self.description,
            'ordernumber': self.ordernumber,
        }


def payment_success(event):
    # XXX: move concrete payment specific changes to bda.plone.payment and
    #      use ZCA for calling
    if event.payment.pid == 'six_payment':
        data = event.data
        order = get_order(event.context, event.order_uid)
        order.attrs['salaried'] = 'yes'
        order.attrs['tid'] = data['tid']


def payment_failed(event):
    # XXX: move concrete payment specific changes to bda.plone.payment and
    #      use ZCA for calling
    if event.payment.pid == 'six_payment':
        data = event.data
        order = get_order(event.context, event.order_uid)
        order.attrs['salaried'] = 'failed'
        order.attrs['tid'] = data['tid']


class OrderTransitions(object):

    def __init__(self, context):
        self.context = context

    def do_transition(self, uid, transition):
        """Do transition for order by UID and transition name.

        @param uid: uuid.UUID or string representing a UUID
        @param transition: string

        @return: order record
        """
        if not isinstance(uid, uuid.UUID):
            uid = uuid.UUID(uid)
        order_data = OrderData(self.context, uid=uid)
        order = order_data.order
        # XXX: currently we need to delete attribute before setting to a new
        #      value in order to persist change. fix in appropriate place.
        if transition == 'mark_salaried':
            del order.attrs['salaried']
            order.attrs['salaried'] = 'yes'
        elif transition == 'mark_outstanding':
            del order.attrs['salaried']
            order.attrs['salaried'] = 'no'
        elif transition == 'renew':
            del order.attrs['state']
            order.attrs['state'] = 'new'
            order_data.decrease_stock(order_data.bookings)
        elif transition == 'finish':
            del order.attrs['state']
            order.attrs['state'] = 'finished'
        elif transition == 'cancel':
            del order.attrs['state']
            order.attrs['state'] = 'cancelled'
            order_data.increase_stock(order_data.bookings)
        else:
            raise ValueError(u"invalid transition: %s" % transition)
        soup = get_soup('bda_plone_orders_orders', self.context)
        soup.reindex(records=[order])
        return order
