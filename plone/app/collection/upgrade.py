import logging

from DateTime import DateTime
from Products.CMFCore.utils import getToolByName
from Products.CMFCore.interfaces._content import IFolderish
from Products.contentmigration.archetypes import InplaceATFolderMigrator
from Products.contentmigration.archetypes import InplaceATItemMigrator
from Products.contentmigration.walker import CustomQueryWalker
from plone.app.querystring.interfaces import IQuerystringRegistryReader
from plone.registry.interfaces import IRegistry
from zope.component import getUtility
from zope.dottedname.resolve import resolve

logger = logging.getLogger('plone.app.collection')
prefix = "plone.app.querystring"

INVALID_OPERATION = 'Invalid operation %s for criterion: %s'
PROFILE_ID = 'profile-plone.app.collection:default'


def format_date(value):
    """Format the date.

    The value is expected to be a DateTime.DateTime object, though it
    actually also works on datetime.datetime objects.

    The query field expects a string with month/date/year.
    So 28 March 2013 should become '03/28/2013'.
    """
    return value.strftime('%m/%d/%Y')


def is_old_non_folderish_item(obj, **kwargs):
    """Is this an old not yet migrated Collection item?

    The old non-folderish and new folderish Collections have the same
    meta_type and portal_type, which means a simple catalog walker
    will crash when it is called on a new folderish Collection, for
    example when the upgrade step is run twice.  We can use this
    function to ignore the new Collections.
    """
    return not IFolderish(obj)


# Converters

class CriterionConverter(object):

    # Last part of the code for the dotted operation method,
    # e.g. 'string.contains'.
    operator_code = ''

    def get_query_value(self, value, index, criterion):
        # value may contain a query and some parameters, but in the
        # simple case it is simply a value.
        return value

    def get_operation(self, value):
        # Get dotted operation method.  This may depend on value.
        return "%s.operation.%s" % (prefix, self.operator_code)

    def is_index_known(self, registry, index):
        # Is the index registered as criterion index?
        key = '%s.field.%s' % (prefix, index)
        try:
            registry.get(key)
        except KeyError:
            logger.error("Index %s is no criterion index. Registry gives "
                         "KeyError: %s", index, key)
            return False
        return True

    def is_index_enabled(self, registry, index):
        # Is the index enabled as criterion index?
        key = '%s.field.%s' % (prefix, index)
        index_data = registry.get(key)
        if index_data.get('enabled'):
            return True
        logger.warn("Index %s is not enabled as criterion index. ", index)
        return False

    def is_operation_valid(self, registry, operation):
        # Check that the operation exists.
        op_info = registry.get(operation)
        if op_info is None:
            logger.error("Operation %r is not defined.", operation)
            return False
        op_function_name = op_info.get('operation')
        try:
            resolve(op_function_name)
        except ImportError:
            logger.error("ImportError for operation %r: %s",
                         operation, op_function_name)
            return False
        return True

    def get_valid_operation(self, registry, index, value):
        key = '%s.field.%s.operations' % (prefix, index)
        operations = registry.get(key)
        operation = self.get_operation(value)
        if not operation in operations:
            return
        if self.is_operation_valid(registry, operation):
            return operation

    def __call__(self, formquery, criterion, registry):
        for index, value in criterion.getCriteriaItems():
            # Check if the index is known and enabled as criterion index.
            if not self.is_index_known(registry, index):
                continue
            self.is_index_enabled(registry, index)
            # TODO: what do we do when this is False?  Raise an
            # Exception?  Continue processing the index and value
            # anyway, now that a warning is logged?  Continue with the
            # next criteria item?

            # Get the operation method.
            operation = self.get_valid_operation(registry, index, value)
            if not operation:
                logger.error(INVALID_OPERATION % (operation, criterion))
                # TODO: raise an Exception?
                continue

            # Get the value that we will query for.
            query_value = self.get_query_value(value, index, criterion)

            # Add a row to the form query.
            row = {'i': index,
                   'o': operation}
            if query_value is not None:
                row['v'] = query_value
            formquery.append(row)


class ATDateCriteriaConverter(CriterionConverter):
    """Handle date criteria.

    Note that there is also ATDateRangeCriterion, which is much
    simpler as it just has two dates.

    In our case we have these valid operations:

    ['plone.app.querystring.operation.date.lessThan',
     'plone.app.querystring.operation.date.largerThan',
     'plone.app.querystring.operation.date.between',
     'plone.app.querystring.operation.date.lessThanRelativeDate',
     'plone.app.querystring.operation.date.largerThanRelativeDate',
     'plone.app.querystring.operation.date.today',
     'plone.app.querystring.operation.date.beforeToday',
     'plone.app.querystring.operation.date.afterToday']

    This code is based on the getCriteriaItems method from
    Products/ATContentTypes/criteria/date.py.  We check the field
    values ourselves instead of translating the values back and forth.
    """

    def __call__(self, formquery, criterion, registry):
        if criterion.value is None:
            return
        field = criterion.Field()
        value = criterion.Value()

        # Check if the index is known and enabled as criterion index.
        if not self.is_index_known(registry, field):
            return
        self.is_index_enabled(registry, field)

        # Negate the value for 'old' days
        if criterion.getDateRange() == '-':
            value = -value

        date = DateTime() + value

        # Get the possible operation methods.
        key = '%s.field.%s.operations' % (prefix, field)
        operations = registry.get(key)

        def add_row(operation, value=None):
            if not operation in operations:
                raise ValueError(INVALID_OPERATION % (operation, criterion))
            if not self.is_operation_valid(registry, operation):
                raise ValueError(INVALID_OPERATION % (operation, criterion))
            # Add a row to the form query.
            row = {'i': field,
                   'o': operation}
            if value is not None:
                row['v'] = value
            formquery.append(row)

        operation = criterion.getOperation()
        if operation == 'within_day':
            if date.isCurrentDay():
                new_operation = "%s.operation.date.today" % prefix
                add_row(new_operation)
                return
            date_range = (date.earliestTime(), date.latestTime())
            new_operation = "%s.operation.date.between" % prefix
            add_row(new_operation, date_range)
            return
        elif operation == 'more':
            if value != 0:
                new_operation = "%s.operation.date.largerThanRelativeDate" % prefix
                add_row(new_operation, value)
                return
            else:
                new_operation = "%s.operation.date.afterToday" % prefix
                add_row(new_operation)
                return
        elif operation == 'less':
            if value != 0:
                new_operation = "%s.operation.date.lessThanRelativeDate" % prefix
                add_row(new_operation, value)
                return
            else:
                new_operation = "%s.operation.date.beforeToday" % prefix
                add_row(new_operation)
                return


class ATSimpleStringCriterionConverter(CriterionConverter):
    operator_code = 'string.contains'


class ATCurrentAuthorCriterionConverter(CriterionConverter):
    operator_code = 'string.currentUser'


class ATSelectionCriterionConverter(CriterionConverter):
    operator_code = 'selection.is'

    def get_query_value(self, value, index, criterion):
        if value.get('operator') == 'and':
            logger.warn("Cannot handle selection operator 'and'. Using 'or'. "
                        "%r", value)
        values = value['query']
        # Special handling for portal_type=Topic.
        if index == 'portal_type' and 'Topic' in values:
            values = list(values)
            values[values.index('Topic')] = 'Collection'
            values = tuple(values)
        return values


class ATListCriterionConverter(ATSelectionCriterionConverter):
    pass


class ATReferenceCriterionConverter(ATSelectionCriterionConverter):
    # Note: the new criterion is disabled by default.  Also, it
    # needs the _referenceIs function in the plone.app.querystring
    # queryparser and that function is not defined.
    operator_code = 'reference.is'


class ATPathCriterionConverter(CriterionConverter):
    operator_code = 'string.path'

    def get_query_value(self, value, index, criterion):
        if not criterion.Recurse():
            logger.warn("Cannot handle non-recursive path search. "
                        "Allowing recursive search. %r", value)
        raw = criterion.getRawValue()
        if not raw:
            return
        if len(raw) > 1:
            logger.warn("Multiple paths in query. Using only the first. %r",
                        value['query'])
        return raw[0]


class ATBooleanCriterionConverter(CriterionConverter):

    def get_operation(self, value):
        # Get dotted operation method.
        # value is one of these beauties:
        # value = [1, True, '1', 'True']
        # value = [0, '', False, '0', 'False', None, (), [], {}, MV]
        if True in value:
            code = 'isTrue'
        elif False in value:
            code = 'isFalse'
        else:
            logger.warn("Unknown value for boolean criterion. "
                        "Falling back to True. %r", value)
            code = 'isTrue'
        return "%s.operation.boolean.%s" % (prefix, code)

    def __call__(self, formquery, criterion, registry):
        for index, value in criterion.getCriteriaItems():
            if index == 'is_folderish':
                fieldname = 'isFolderish'
            elif index == 'is_default_page':
                fieldname = 'isDefaultPage'
            else:
                fieldname = index
            # Check if the index is known and enabled as criterion index.
            if not self.is_index_known(registry, fieldname):
                continue
            self.is_index_enabled(registry, fieldname)
            # Get the operation method.
            operation = self.get_valid_operation(registry, fieldname, value)
            if not operation:
                logger.error(INVALID_OPERATION % (operation, criterion))
                # TODO: raise an Exception?
                continue
            # Add a row to the form query.
            row = {'i': index,
                   'o': operation}
            formquery.append(row)


class ATDateRangeCriterionConverter(CriterionConverter):
    operator_code = 'date.between'

    def get_query_value(self, value, index, criterion):
        return value['query']


class ATPortalTypeCriterionConverter(CriterionConverter):
    operator_code = 'selection.is'

    def get_query_value(self, value, index, criterion):
        # Special handling for portal_type=Topic.
        if 'Topic' in value:
            value = list(value)
            value[value.index('Topic')] = 'Collection'
            value = tuple(value)
        return value


class ATRelativePathCriterionConverter(CriterionConverter):
    # We also have path.isWithinRelative, but its function is not defined.
    operator_code = 'string.relativePath'

    def get_query_value(self, value, index, criterion):
        if not criterion.Recurse():
            logger.warn("Cannot handle non-recursive path search. "
                        "Allowing recursive search. %r", value)
        return criterion.getRelativePath()


class ATSimpleIntCriterionConverter(CriterionConverter):
    # Also available: int.lessThan, int.largerThan.
    operator_code = 'int.is'

    def get_operation(self, value):
        # Get dotted operation method.
        direction = value.get('range')
        if not direction:
            code = 'is'
        elif direction == 'min':
            code = 'largerThan'
        elif direction == 'max':
            code = 'lessThan'
        elif direction == 'min:max':
            logger.warn("min:max direction not supported for integers. %r",
                        value)
            return
        else:
            logger.warn("Unknown direction for integers. %r", value)
            return
        return "%s.operation.int.%s" % (prefix, code)

    def get_query_value(self, value, index, criterion):
        if isinstance(value['query'], tuple):
            logger.warn("More than one integer is not supported. %r", value)
            return
        return value['query']


class TopicMigrator(InplaceATFolderMigrator):
    src_portal_type = 'Topic'
    src_meta_type = 'ATTopic'
    dst_portal_type = dst_meta_type = 'Collection'
    view_methods_mapping = {
        'folder_listing': 'standard_view',
        'folder_summary_view': 'summary_view',
        'folder_full_view': 'all_content',
        'folder_tabular_view': 'tabular_view',
        'atct_album_view': 'thumbnail_view',
        'atct_topic_view': 'standard_view',
        }

    @property
    def registry(self):
        return self.kwargs['registry']

    def last_migrate_layout(self):
        """Migrate the layout (view method).

        This needs to be done last, as otherwise our changes in
        migrate_criteria may get overriden by a later call to
        migrate_properties.
        """
        if self.old.getCustomView():
            # Previously, the atct_topic_view had logic for showing
            # the results in a list or in tabular form.  If
            # getCustomView is True, this means the new object should
            # use the tabular view.
            self.new.setLayout('tabular_view')
            return

        layout = self.view_methods_mapping.get(self.old.getLayout())
        if layout:
            self.new.setLayout(layout)

    def beforeChange_criteria(self):
        """Store the criteria of the old Topic.

        Store the info on the migrator and restore the values in the
        migrate_criteria method.
        """
        self._collection_sort_reversed = None
        self._collection_sort_on = None
        self._collection_query = None
        path = '/'.join(self.old.getPhysicalPath())
        logger.info("Migrating Topic at %s", path)
        # Get the old criteria.
        # See also Products.ATContentTypes.content.topic.buildQuery
        criteria = self.old.listCriteria()
        logger.debug("Old criteria for %s: %r", path,
                     [(crit, crit.getCriteriaItems()) for crit in criteria])
        formquery = []
        for criterion in criteria:
            type_ = criterion.__class__.__name__
            if type_ == 'ATSortCriterion':
                # Sort order and direction are now stored in the Collection.
                self._collection_sort_reversed = criterion.getReversed()
                self._collection_sort_on = criterion.Field()
                logger.debug("Sort on %r, reverse: %s.",
                             self._collection_sort_on,
                             self._collection_sort_reversed)
                continue

            converter = CONVERTERS.get(type_)
            if converter is None:
                msg = 'Unsupported criterion %s' % type_
                logger.error(msg)
                raise ValueError(msg)
            converter(formquery, criterion, self.registry)

        logger.debug("New query for %s: %r", path, formquery)
        self._collection_query = formquery

    def migrate_criteria(self):
        """Migrate old style to new style criteria.

        Plus handling for some special fields.
        """
        # The old Topic has boolean limitNumber and integer itemCount,
        # where the new Collection only has limit.
        if self.old.getLimitNumber():
            self.new.setLimit(self.old.getItemCount())

        # Get the old data stores by the beforeChange_criteria method.
        if self._collection_sort_reversed is not None:
            self.new.setSort_reversed(self._collection_sort_reversed)
        if self._collection_sort_on is not None:
            self.new.setSort_on(self._collection_sort_on)
        if self._collection_query is not None:
            self.new.setQuery(self._collection_query)


class FolderishCollectionMigrator(InplaceATItemMigrator):
    src_portal_type = src_meta_type = 'Collection'
    dst_portal_type = dst_meta_type = 'Collection'


def migrate_to_folderish_collections(context):
    """Migrate new-style Collections to folderish Collections.

    This can be used as upgrade step.

    The new-style Collections started out as inheriting from
    ATDocument.  Historically users could nest topics, so we want to
    try to bring that back.  This is the first step: make existing
    new-style Collections folderish.

    TODO/notes:

    - This simple migration seems to work.

    - The sub collection should 'inherit' the query from its parent,
      otherwise this exercise does not make much sense.  See the
      maurits-recursive branch of archetypes.querywidget, which seems
      to work, though for the tests to pass it currently needs the
      maurits-upgradepath branch of plone.app.collection.

    """
    site = getToolByName(context, 'portal_url').getPortalObject()
    collection_walker = CustomQueryWalker(
        site, FolderishCollectionMigrator,
        callBefore=is_old_non_folderish_item)
    collection_walker.go()


def run_typeinfo_step(context):
    context.runImportStepFromProfile(PROFILE_ID, 'typeinfo')


def run_actions_step(context):
    context.runImportStepFromProfile(PROFILE_ID, 'actions')


def run_propertiestool_step(context):
    context.runImportStepFromProfile(PROFILE_ID, 'propertiestool')


def migrate_topics(context):
    """Migrate ATContentTypes Topics to plone.app.collection Collections.

    This can be used as upgrade step.

    The new-style Collections might again get some changes later.
    They may become folderish or dexterity items or dexterity
    containers or a dexterity behavior.

    For the moment this is just for the 1.x Collections.  Nested
    Topics cannot be migrated for the moment and may give an error.
    """
    site = getToolByName(context, 'portal_url').getPortalObject()
    topic_walker = CustomQueryWalker(site, TopicMigrator)
    # Parse the registry to get allowed operations and pass it to the
    # migrator.
    reg = getUtility(IRegistry)
    reader = IQuerystringRegistryReader(reg)
    registry = reader.parseRegistry()
    topic_walker.go(registry=registry)


CONVERTERS = {
    # Create an instance of each converter.
    'ATBooleanCriterion': ATBooleanCriterionConverter(),
    'ATCurrentAuthorCriterion': ATCurrentAuthorCriterionConverter(),
    'ATDateCriteria': ATDateCriteriaConverter(),
    'ATDateRangeCriterion': ATDateRangeCriterionConverter(),
    'ATListCriterion': ATListCriterionConverter(),
    'ATPathCriterion': ATPathCriterionConverter(),
    'ATPortalTypeCriterion': ATPortalTypeCriterionConverter(),
    'ATReferenceCriterion': ATReferenceCriterionConverter(),
    'ATRelativePathCriterion': ATRelativePathCriterionConverter(),
    'ATSelectionCriterion': ATSelectionCriterionConverter(),
    'ATSimpleIntCriterion': ATSimpleIntCriterionConverter(),
    'ATSimpleStringCriterion': ATSimpleStringCriterionConverter(),
    }
