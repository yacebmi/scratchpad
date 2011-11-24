################################################################
# Plone ini-style importer
#
# Written by Andreas Jung
# (C) 2008, ZOPYX Ltd. & Co. KG, D-72070 TÃ¼bingen
################################################################

import os
import shutil
import tempfile
import glob
import transaction
from datetime import datetime
from ConfigParser import ConfigParser
from Products.CMFPlone.utils import _createObjectByType
from Testing.makerequest import makerequest


default_products = ['Anbieter', 'Jobs']

handlers = dict()  # ident -> handler

def registerHandler(handler):
    handlers[handler.ident] = handler


def setup_plone(app, products=default_products, profiles=[]):

    app = makerequest(app)

    plone_id = datetime.now().strftime('%Y%m%d-%H%M%S')
    factory = app.manage_addProduct['CMFPlone']
    factory.addPloneSite(plone_id, create_userfolder=True, extension_ids=profiles)

    plone = app[plone_id]
    qit = plone.portal_quickinstaller

    ids = [ x['id'] for x in qit.listInstallableProducts(skipInstalled=1) ]
    for product in products:
        if product in ids:
            qit.installProduct(product)

    if 'front-page' in plone.objectIds():
        plone.manage_delObjects('front-page')

    return plone


def import_members(plone, import_dir, verbose):

    print 'Importing members'

    pr = plone.portal_registration
    pm = plone.portal_membership

    members_ini = os.path.join(import_dir, 'members.ini')

    CP = ConfigParser()
    CP.read([members_ini])
    get = CP.get

    for section in CP.sections():
        username = get(section, 'username')
        if verbose:
            print '-> %s' % username

        # omit group accounts
        if username.startswith('group_'):
            continue

        try:
            pr.addMember(username, get(section, 'password'))
        except:
            print '-> ERROR: omitting %s' % username
            continue
        member = pm.getMemberById(username)
        pm.createMemberArea(username)
        member.setMemberProperties(dict(email=get(section, 'email'),
                                        fullname=get(section, 'fullname'),
                                  ))


class BaseHandler(object):

    portal_types = ()
    ident = None
    initialized = False

    def __init__(self, plone, import_dir, cfgfile, verbose=False):
        self.plone = plone
        self.portal_id = plone.getId()
        self.portal_path = plone.absolute_url(1)
        self.import_dir = import_dir
        self.verbose = verbose
        self.cfg = ConfigParser()
        self.cfg.read(cfgfile)

    def new_id(self, context, id):

        if not id in context.objectIds():
            return id

        count = 2
        running = True
        while running:
            new_id = id + '.%d' % count
            if not new_id in context.objectIds():
                return new_id
            count += 1


    def changeOwner(self, context, owner):

        try:
            context.plone_utils.changeOwnershipOf(context, owner)
        except:
            try:
                context.plone_utils.changeOwnershipOf(context, 'raetsch')
            except:
                if not 'admin' in context.portal_membership.listMemberIds():
                    pm = context.portal_registration.addMember('admin', '"&§%/!')
                context.plone_utils.changeOwnershipOf(context, 'admin')



    def folder_create(self, root, dirname):

        current = root
        for c in dirname.split('/'):
            if not c: continue
            if not c in current.objectIds():
                _createObjectByType('Folder', current, id=c)
#                current.invokeFactory('Folder', id=c)
            current = getattr(current, c)

        return current

    def set_data(self, obj, section):

        CP = self.cfg

        if CP.has_option(section, 'description'):
            obj.setDescription(CP.get(section, 'description'))

        if CP.has_option(section, 'title'):
            obj.setTitle(CP.get(section, 'title'))

        if CP.has_option(section, 'expires'):
            obj.setExpirationDate(CP.getfloat(section, 'expires'))

        if CP.has_option(section, 'effective'):
            obj.setEffectiveDate(CP.getfloat(section, 'effective'))

        if CP.has_option(section, 'created'):
            obj.setCreationDate(CP.getfloat(section, 'created'))

        if CP.has_option(section, 'content-type'):
            obj.setContentType(CP.get(section, 'content-type'))

        if CP.has_option(section, 'text-format'):
            format = CP.get(section, 'text-format')
            if format == 'structured-text':
                format = 'text/structured'
            elif format == 'html':
                format = 'text/html'
            obj.format = format
            obj.setFormat(format)
            obj.__format = format

        if CP.has_option(section, 'subjects'):
            subjects = [s.strip() for s in CP.get(section, 'subjects').split(',')]
            obj.setSubject(subjects)

        if CP.has_option(section, 'owner'):
            owner = CP.get(section, 'owner')
            self.changeOwner(obj, owner)
            obj.setCreators([owner])

        if CP.has_option(section, 'review-state'):
            state = CP.get(section, 'review-state')
            if state == 'published':
                wf_tool = obj.portal_workflow
                try:
                    wf_tool.doActionFor(obj, 'publish') 
                except:
                    pass


    def get_binary(self, section, key='filename'):
        return file(self.cfg.get(section, key)).read()


    def __call__(self, *args, **kw):

        portal_type = getattr(self, 'portal_type', None)
        if portal_type is None:
            print 'Omitting %s' % self.__class__.__name__
            return 

        print 'Importing %s' % portal_type

        get = self.cfg.get

        for section in self.cfg.sections():
            path = get(section, 'path')
            id = get(section, 'id')

            if getattr(self, 'folderish', False):
                dirname = path
            else:
                dirname = '/'.join(path.split('/')[:-1])
            folder = self.folder_create(self.plone, dirname)

            if self.verbose:
                print 'Creating %s: %s' % (portal_type, path)
#            id = self.new_id(folder, id)

            if id in folder.objectIds():
                obj = folder
            else:
                _createObjectByType(portal_type, folder, id)
            obj = getattr(folder, id)
            self.set_data(obj, section)

            if hasattr(self, 'import2'):
                self.import2(obj, section)


class NewsItemHandler(BaseHandler):
    ident = 'newsitem'
    portal_type = 'News Item'

    def import2(self, obj, section):
        obj.setText(self.get_binary(section))

registerHandler(NewsItemHandler)

class DocumentHandler(BaseHandler):
    ident = 'documents'
    portal_type = 'Document'

    def import2(self, obj, section):
        obj.setText(self.get_binary(section))

registerHandler(DocumentHandler)

class FolderHandler(BaseHandler):
    ident = 'folder'
    portal_type = 'Folder'
    folderish = True

registerHandler(FolderHandler)


class NewsHandler(BaseHandler):
    ident = 'newitem'
    portal_type = 'News Item'

    def import2(self, obj, section):
        obj.setText(self.get_binary(section))

registerHandler(NewsHandler)

class JobGesuchHandler(BaseHandler):
    ident = 'jobgesuch'
    portal_type = 'JobGesuch'

    def import2(self, obj, section):
        try:
            obj.setBeschreibung(self.get_binary(section, 'filename-beschreibung'))
            obj.setKontakt(self.get_binary(section, 'filename-kontakt'))
        except:
            pass

registerHandler(JobGesuchHandler)

class JobAngebotHandler(BaseHandler):
    ident = 'jobangebot'
    portal_type = 'JobAngebot'

    def import2(self, obj, section):
        try:
            obj.setBeschreibung(self.get_binary(section, 'filename-beschreibung'))
            obj.setKontakt(self.get_binary(section, 'filename-kontakt'))
            obj.setOrt(self.cfg.get(section, 'ort'))
            obj.setBefristet(eval(self.cfg.get(section, 'befristet')))
        except:
            pass

registerHandler(JobAngebotHandler)

class AnbieterHandler(BaseHandler):
    ident = 'anbieter'
    portal_type = 'Anbieter'


    def import2(self, obj, section):
        schema = obj.Schema()
        for name in ('firmenname',
                    'ansprechpartner_anrede',
                    'ansprechpartner_vorname',
                    'ansprechpartner_nachname',
                    'ansprechpartner',
                    'strasse',
                    'plz',
                    'ort',
                    'plz_bereich',
                    'country',
                    'telefon',
                    'fax',
                    'email',
                    'leistungsbeschreibung',
                    'url_homepage',
                    'course_provider',
                    'courses_url',
                    'dzug_vereins_mitglied',):

            value = self.cfg.get(section, name)
            field = schema[name]
            mutator = field.mutator
            getattr(obj, mutator)(value)

registerHandler(AnbieterHandler)

class LinkHandler(BaseHandler):
    ident = 'link'
    portal_type = 'Link'

    def import2(self, obj, section):
        obj.setRemoteUrl(self.cfg.get(section, 'url'))

registerHandler(LinkHandler)


class ImageHandler(BaseHandler):
    ident = 'image'
    portal_type = 'Image'

    def import2(self, obj, section):
        obj.setImage(self.get_binary(section))

registerHandler(ImageHandler)

class ZWikiPageHandler(BaseHandler):
    ident = 'zwikipage'
    portal_type = 'Wiki Page'

    def import2(self, obj, section):
        folder = obj.aq_parent
        folder.manage_delObjects(self.cfg.get(section, 'id'))
        try:
            folder._importObjectFromFile(self.cfg.get(section, 'filename'))
        except:
            print 'Error: ZWIKI %s' % self.cfg.get(section, 'filename')

registerHandler(ZWikiPageHandler)

class CMFBibliographyHandler(BaseHandler):
    ident = 'cmbibliography'
    portal_type = 'BibliographyFolder'

    def import2(self, obj, section):
        folder = obj.aq_parent
        folder.manage_delObjects(self.cfg.get(section, 'id'))
        folder._importObjectFromFile(self.cfg.get(section, 'filename'))

registerHandler(CMFBibliographyHandler)


class FileHandler(BaseHandler):
    ident = 'files'
    portal_type = 'File'

    def import2(self, obj, section):
        obj.setFile(self.get_binary(section))

registerHandler(FileHandler)


def fixup(plone):
    """ perform post-migration actions """

    for obj in plone.objectValues():
        try:
            obj.setExcludeFromNav(True)
            obj.reindexObject()
        except AttributeError:
            pass

    for brain in plone.portal_catalog(portal_type=('Document', 'NewsItem')):
        obj = brain.getObject()
        obj.setFormat('text/structured')



def import_plone(self, import_dir, verbose=False, migration_profile=None):

    print '-'*80    
    print 'Importing Plone site from %s ' % import_dir
    print '-'*80    

    products = default_products
    profiles = []

    if migration_profile:
        CP = ConfigParser()
        CP.read(migration_profile)
        if CP.has_option('default', 'profiles'):
            v = CP.get('default', 'profiles')
            profiles.extend([profile.strip() for profile in v.split()])
        if CP.has_option('default', 'products'):
            v = CP.get('default', 'products')
            products.extend([product.strip() for product in v.split()])


    plone = setup_plone(self, products, profiles)
    transaction.commit()
    print 'Site created: %s' % plone.getId()
    print 'Products: %s' % ','.join(products)
    print 'Profiles: %s' % profiles

    import_members(plone, import_dir, verbose)
    transaction.commit()

    for fname in glob.glob('%s/*.ini' % import_dir):
        if fname.endswith('members.ini'): continue
        ident = os.path.splitext(os.path.basename(fname))[0]
        handler = handlers[ident](plone, import_dir, fname, verbose)
        handler()
        transaction.commit()

    fixup(plone)
    transaction.commit()

    return plone.absolute_url()


if __name__ == '__main__':

    from optparse import OptionParser
    from AccessControl.SecurityManagement import newSecurityManager
    import Zope

    parser = OptionParser()
    parser.add_option('-u', '--user', dest='username', default='admin')
    parser.add_option('-m', '--migration-profile', dest='migration_profile', default=None)
    parser.add_option('-v', '--verbose', dest='verbose', action='store_true',
                      default=False)

    options, args = parser.parse_args()

    for import_dir in args:

        app = Zope.app()
        uf = app.acl_users
        user = uf.getUser(options.username)
        if user is None:
            raise ValueError('Unknown user: %s' % options.username)
        newSecurityManager(None, user.__of__(uf))

        url = import_plone(app, import_dir, options.verbose, options.migration_profile)
        print 'Committing...'
        transaction.commit()
        print 'done'
        print url
