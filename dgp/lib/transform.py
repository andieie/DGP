# coding=utf-8

"""
transform.py
Library for data transformation classes
"""

from copy import deepcopy
from pandas import DataFrame
import inspect
from functools import wraps

from dgp.lib.etc import gen_uuid, dedup_dict

transform_class_dict = {}

def createtransformclass(class_id):
    def decorator(func):
        sig = inspect.signature(func)
        var_list = []
        for param in sig.parameters.values():
        # positional arguments only for data
        # kwonly args for other parameters
            if param.kind == param.KEYWORD_ONLY:
                if param.default is not param.empty:
                    var_list.append((param.name, param.default))
                else:
                    var_list.append(param.name)
        def class_func(self, *args, **kwargs):
            return func(*args, **kwargs)

        cls = type(class_id, (Transform,),
                   dict(func=class_func, var_list=var_list))
        transform_class_dict[class_id] = cls

        @wraps(func)
        def wrapper(*args, **kwargs):
            return cls(*args, **kwargs)
        return wrapper
    return decorator


class RegisterTransformClass:
    """
    Class decorator for constructing transforms. Use the decorator when
    defining transform classes to submit the transform into the registry.

    Parameters
    ----------
        name : string
            The string by which the transform is identified in the registry.
    """
    def __init__(self, class_id):
        self.class_id = class_id

    def __call__(self, cls):
        transform_class_dict[self.class_id] = cls
        return cls

    @staticmethod
    def get_class_from_id(class_id):
        return transform_class_dict.get(class_id)


@RegisterTransformClass(None)
class Transform:
    """
    Transform base class.

    All transform classes should subclass this one.

    The class instance is callable. Any parameters not specified when called
    are filled in by the values set in the instance variables that correspond
    with those parameters. Instance variables are specified in the variable
    `var_list`.

    The same transform with different parameters can be generated by making a
    new instance and setting the instance variables accordingly.

    Each instance is given a unique id.

    """
    var_list = None

    def __init__(self, **kwargs):
        self._uid = gen_uuid('xf')
        if self.var_list is None:
            raise ValueError('Must set `var_list` variable. (class={cls})'
                             .format(cls=self.__class__.__name__))

        for var in self.var_list:
            if isinstance(var, tuple):
                name, val = var
            else:
                name = var
                val = None

            if getattr(self, name, None) is None:
                setattr(self, name, val)

        for k, v in kwargs.items():
            if getattr(self, name, None) is not None:
                setattr(self, k, v)

    @property
    def uid(self):
        return self._uid

    def __call__(self, *args, **kwargs):
        # identify arguments that are instance variables
        argspec = inspect.getfullargspec(self.func)
        keywords = {}
        for arg in self.var_list:
            if isinstance(arg, tuple):
                name = arg[0]
            else:
                name = arg

            if name in argspec.args:
                keywords[name] = self.__dict__[name]

        # override keywords explicitly set in function call
        for k, v in kwargs.items():
            keywords[k] = v
        return self.func(*args, **keywords)

    def __str__(self):
        return '{cls}({uid})'.format(cls=self.__class__.__name__,
                                     uid=self._uid)


class TransformChain:
    def __init__(self):
        self._uid = gen_uuid('tc')
        self._transforms = {}
        self._ordering = []

    @property
    def uid(self):
        return self._uid

    @property
    def ordering(self):
        return self._ordering

    def addtransform(self, transform):
        if callable(transform):
            uid = gen_uuid('tf')
            self._transforms[uid] = transform
            self._ordering.append(uid)
            return (uid, self._transforms[uid])
        else:
            return None

    def removetransform(self, uid):
        del self._transforms[uid]
        self._ordering.remove(uid)

    def reorder(self, reordering):
        """
        Change the order of application of transforms. Input is a dictionary
        with transform uid's as keys and position as values.
        """
        d = dedup_dict(reordering)
        order = sorted(d.keys(), key=d.__getitem__)
        for uid in order:
            self._ordering.remove(uid)
            self._ordering.insert(d[uid], uid)
        return self.ordering

    def apply(self, df, **kwargs):
        """
        Makes a deep copy of the target DataFrame and applies the transforms in
        the order specified.
        """
        df_cp = deepcopy(df)
        for uid in self._ordering:
            df_cp = self._transforms[uid](df_cp, **kwargs)
        return df_cp

    def __len__(self):
        return len(self._transforms.items())

    def __str__(self):
        return 'TransformChain({uid})'.format(uid=self._uid)

    def __getitem__(self, key):
        return self._ordering[key]

    def __iter__(self):
        for uid in self._ordering:
            yield self._transforms[uid]


class DataWrapper:
    """
    A container for transformed DataFrames. Multiple transform chains may
    be specified and the resultant DataFrames will be held in this class
    instance.
    """
    def __init__(self, frame: DataFrame):
        self.df = frame # original DataFrame; not ever modified
        self.modified = {}
        self._transform_chains = {}
        self._defaultchain = None

    def removechain(self, uid):
        del self._transform_chains[uid]
        del self.modified[uid]

    def applychain(self, tc):
        if not isinstance(tc, TransformChain):
            raise TypeError('expected an instance or subclass of '
                            'TransformChain, but got ({typ})'.format(type(tc)))

        if tc.uid not in self._transform_chains:
            self._transform_chains[tc.uid] = tc
            if self._defaultchain is None:
                self._defaultchain = self._transform_chains[tc.uid]
        self.modified[tc.uid] = self._transform_chains[tc.uid].apply(self.df)
        return self.modified[tc.uid]

    @property
    def data(self, reapply=False):
        if self._defaultchain is not None:
            if reapply:
                return self.applychain(self._defaultchain)
            else:
                return self.modified[self._defaultchain.uid]
        else:
            return self.df

    def __len__(self):
        return len(self.modified.items())
