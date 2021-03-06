from zope.interface import alsoProvides
from plone.app.testing import IntegrationTesting
from plone.app.testing import PLONE_FIXTURE
from plone.app.testing import PloneSandboxLayer
from bda.plone.orders.interfaces import IOrdersExtensionLayer


def set_browserlayer(request):
    """Set the BrowserLayer for the request.

    We have to set the browserlayer manually, since importing the profile alone
    doesn't do it in tests.
    """
    alsoProvides(request, IOrdersExtensionLayer)


class OrdersLayer(PloneSandboxLayer):
    defaultBases = (PLONE_FIXTURE,)

    def setUpZope(self, app, configurationContext):
        import bda.plone.orders
        self.loadZCML(package=bda.plone.orders,
                      context=configurationContext)

    def setUpPloneSite(self, portal):
        self.applyProfile(portal, 'bda.plone.orders:default')

    def tearDownZope(self, app):
        pass


Orders_FIXTURE = OrdersLayer()
Orders_INTEGRATION_TESTING = IntegrationTesting(
    bases=(Orders_FIXTURE,),
    name="Orders:Integration")
