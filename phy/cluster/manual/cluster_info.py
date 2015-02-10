# -*- coding: utf-8 -*-

"""Cluster metadata structure."""

#------------------------------------------------------------------------------
# Imports
#------------------------------------------------------------------------------

from collections import defaultdict, OrderedDict
from copy import deepcopy

from ...utils._color import _random_color
from ...utils._misc import _as_dict, _fun_arg_count
from ...ext.six import iterkeys, itervalues, iteritems
from ._utils import _unique, _spikes_in_clusters
from ._update_info import UpdateInfo
from ._history import History


#------------------------------------------------------------------------------
# BaseClusterInfo class
#------------------------------------------------------------------------------

def _default_value(field, default, cluster):
    """Return the default value of a field."""
    if hasattr(default, '__call__'):
        if _fun_arg_count(default) == 0:
            return default()
        elif _fun_arg_count(default) == 1:
            return default(cluster)
    else:
        return default


def _default_info(fields, cluster):
    """Default structure holding info of a cluster."""
    fields = _as_dict(fields)
    return dict([(field, _default_value(field, default, cluster))
                 for field, default in iteritems(fields)])


class ClusterDefaultDict(defaultdict):
    """Like a defaultdict, but the factory function can accept the key
    as argument."""
    def __init__(self, factory=None):
        self._factory = factory
        if factory is not None:
            self._n_args = _fun_arg_count(factory)
        else:
            self._n_args = None
        super(ClusterDefaultDict, self).__init__(factory)

    def __missing__(self, key):
        if self._n_args == 1:
            # Call the factory with the cluster number as argument
            # and save the result in the defaultdict.
            self[key] = value = self._factory(key)
            return value
        else:
            return super(ClusterDefaultDict, self).__missing__(key)


def _cluster_info(fields, data=None):
    """Initialize a structure holding cluster metadata."""
    if data is None:
        data = {}
    out = ClusterDefaultDict(lambda cluster: _default_info(fields, cluster))
    for cluster, values in iteritems(data):
        # Create the default cluster info dict.
        info = out[cluster]
        # Update the specified values, so that the default values are used
        # for the unspecified values.
        for key, value in iteritems(values):
            info[key] = value
    return out


class BaseClusterInfo(object):
    # TODO: unit tests for BaseClusterInfo
    """Hold information about clusters."""
    def __init__(self, data=None, fields=None):
        # 'fields' is a list of tuples (field_name, default_value).
        # 'self._fields' is an OrderedDict {field_name ==> default_value}.
        self._fields = _as_dict(fields)
        self._field_names = list(iterkeys(self._fields))
        # '_data' maps cluster labels to dict (field => value).
        self._data = _cluster_info(fields, data=data)

    @property
    def data(self):
        """Dictionary holding data for all clusters."""
        return self._data

    def __getitem__(self, cluster):
        return self._data[cluster]

    def set(self, clusters, field, values):
        """Set some information for a number of clusters."""
        # Ensure 'clusters' is a list of clusters.
        if not hasattr(clusters, '__len__'):
            clusters = [clusters]
        if hasattr(values, '__len__'):
            assert len(clusters) == len(values)
            for cluster, value in zip(clusters, values):
                self._data[cluster][field] = value
        else:
            for cluster in clusters:
                self._data[cluster][field] = values

    def unset(self, clusters):
        """Delete a cluster."""
        if not hasattr(clusters, '__len__'):
            clusters = [clusters]
        for cluster in clusters:
            if cluster in self._data:
                del self._data[cluster]


#------------------------------------------------------------------------------
# Global variables related to cluster metadata
#------------------------------------------------------------------------------

DEFAULT_GROUPS = [
    (0, 'Noise'),
    (1, 'MUA'),
    (2, 'Good'),
    (3, 'Unsorted'),
]


DEFAULT_FIELDS = {
    'group': 3,
    'color': _random_color,
}


#------------------------------------------------------------------------------
# ClusterMetadata class
#------------------------------------------------------------------------------

class ClusterMetadata(BaseClusterInfo):
    """Object holding cluster metadata.

    Constructor
    -----------

    fields : list
        List of tuples (field_name, default_value).
    data : dict-like
        Initial data.

    """

    def __init__(self, data=None, fields=None):
        if fields is None:
            fields = DEFAULT_FIELDS
        super(ClusterMetadata, self).__init__(data=data, fields=fields)
        # Keep a deep copy of the original structure for the undo stack.
        self._data_base = deepcopy(self._data)
        # The stack contains (clusters, field, value, update_info) tuples.
        self._undo_stack = History((None, None, None, None))

    def set(self, clusters, field, values, add_to_stack=True):
        """Set some information for a number of clusters and add the changes
        to the undo stack."""
        # Ensure 'clusters' is a list of clusters.
        if not hasattr(clusters, '__len__'):
            clusters = [clusters]
        super(ClusterMetadata, self).set(clusters, field, values)
        info = UpdateInfo(description=field, metadata_changed=clusters)
        if add_to_stack:
            self._undo_stack.add((clusters, field, values, info))
        return info

    def undo(self):
        """Undo the last metadata change."""
        args = self._undo_stack.back()
        if args is None:
            return
        self._data = deepcopy(self._data_base)
        for clusters, field, values, _ in self._undo_stack:
            if clusters is not None:
                self.set(clusters, field, values, add_to_stack=False)
        # Return the UpdateInfo instance of the undo action.
        info = args[-1]
        return info

    def redo(self):
        """Redo the next metadata change."""
        args = self._undo_stack.forward()
        if args is None:
            return
        clusters, field, values, info = args
        self.set(clusters, field, values, add_to_stack=False)
        # Return the UpdateInfo instance of the redo action.
        return info


#------------------------------------------------------------------------------
# ClusterStats class
#------------------------------------------------------------------------------

class ClusterStats(BaseClusterInfo):
    """Hold cluster statistics with cache.

    Initialized as:

        ClustersStats(my_stat=my_function)

    where `my_function(cluster)` returns a cluster statistics.

    ClusterStats handles the caching logic. It provides an
    `invalidate(clusters)` method.

    """
    def __init__(self, **functions):
        # Set the methods.
        for name, fun in functions.items():
            setattr(self, name, lambda cluster: self[cluster][name])
        super(ClusterStats, self).__init__(fields=functions)

    def invalidate(self, clusters):
        """Invalidate clusters from the cache."""
        self.unset(clusters)