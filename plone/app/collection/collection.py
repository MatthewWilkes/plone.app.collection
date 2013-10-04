# -*- coding: utf-8 -*-
from Products.CMFCore.utils import getToolByName

from plone.app.contentlisting.interfaces import IContentListing

from plone.app.querystring.querybuilder import QueryBuilder

from plone.dexterity.content import Item


class Collection(Item):

    #security.declareProtected(View, 'listMetaDataFields')
    def listMetaDataFields(self, exclude=True):
        """Return a list of all metadata fields from portal_catalog.
        """
        return []
        #tool = getToolByName(self, ATCT_TOOLNAME)
        #return tool.getMetadataDisplay(exclude)

    def results(self, batch=True, b_start=0, b_size=None,
                sort_on=None, limit=None):
        querybuilder = QueryBuilder(self, self.REQUEST)

        kw_args = {
            'query': self.query,
            'batch': batch,
            'b_start': b_start,
            'sort_order': 'reverse' if self.sort_reversed else 'ascending'
        }

        if b_size:
            kw_args['b_size'] = b_size
        if limit:
            kw_args['limit'] = limit
        if sort_on:
            kw_args['sort_on'] = sort_on

        if not b_size and self.item_count:
            kw_args['b_size'] = self.item_count
        if not sort_on and self.sort_on:
            kw_args['sort_on'] = self.sort_on
        if not limit and self.limit:
            kw_args['limit'] = self.limit

        return querybuilder(**kw_args)

    def selectedViewFields(self):
        """Returns a list of all metadata fields from the catalog that were
           selected.
        """
        return []
        #_mapping = {}
        #for field in self.listMetaDataFields().items():
        #    _mapping[field[0]] = field
        #return [_mapping[field] for field in self.customViewFields]

    def getFoldersAndImages(self):
        catalog = getToolByName(self, 'portal_catalog')
        results = self.results(batch=False)

        _mapping = {'results': results, 'images': {}}
        portal_atct = getToolByName(self, 'portal_atct')
        image_types = getattr(portal_atct, 'image_types', [])

        for item in results:
            item_path = item.getPath()
            if item.isPrincipiaFolderish:
                query = {
                    'portal_type': image_types,
                    'path': item_path,
                }
                _mapping['images'][item_path] = IContentListing(catalog(query))
            elif item.portal_type in image_types:
                _mapping['images'][item_path] = [item, ]

        _mapping['total_number_of_images'] = sum(map(
            len,
            _mapping['images'].values()
        ))
        return _mapping

    # BBB

    def setQuery(self, query):
        self.query = query

    def getQuery(self):
        return self.query

    def setSort_on(self, sort_on):
        self.sort_on = sort_on

    def setSort_reversed(self, sort_reversed):
        self.sort_reversed = sort_reversed

    def queryCatalog(self, batch=True, b_start=0, b_size=30, sort_on=None):
        return self.results(
            batch, b_start, b_size, sort_on=sort_on
        )
