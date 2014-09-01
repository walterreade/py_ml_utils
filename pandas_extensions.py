'''
Naming Conventions for Features:
c_ = categorical
i_ = categoricals as indexes
n_ = numerical
b_ = binary
d_ = date

TODO:
- Time series computations 
  see: http://pandas.pydata.org/pandas-docs/stable/computation.html
- Assume all methods destructive
- Try pandas vs numpy sparse arrays
'''

import pandas as pd
import numpy as np
from misc import *
from ast_parser import *
from sklearn.preprocessing import OneHotEncoder
from scipy import sparse
import itertools, logging, time, datetime

logging.basicConfig(level=logging.DEBUG, 
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)
t0 = time.time()

def debug(msg): log.info(msg)

def start(msg): 
  global t0
  t0 = time.time()
  log.info(msg)

def stop(msg): 
  global t0
  log.info(msg + (', took (h:m:s): %s' % 
    datetime.timedelta(seconds=time.time() - t0)))
  t0 = time.time()

'''
Series Extensions
'''
def _s_one_hot_encode(self):
  start('one_hot_encoding column')  
  df = pd.get_dummies(self)
  stop('done one_hot_encoding column converted to ' + 
      `df.shape[1]` + ' columns')  
  return df

def _s_bin(self, n_bins=100):
  return pd.Series(pd.cut(self, n_bins))

'''
DataFrame Extensions
'''

def _df_categoricals(self): return filter(lambda c: c.startswith('c_'), self.columns)
def _df_indexes(self): return filter(lambda c: c.startswith('i_'), self.columns)
def _df_numericals(self): return filter(lambda c: c.startswith('n_'), self.columns)
def _df_binaries(self): return filter(lambda c: c.startswith('b_'), self.columns)
def _df_dates(self): return filter(lambda c: c.startswith('d_'), self.columns)

def _df_one_hot_encode(self, dtype=np.float):
  start('one_hot_encoding data frame with ' + `self.shape[1]` + \
    ' columns. note: this resturns a sparse array and empties' + \
    ' the initial array.')  
  if self.categoricals(): self.to_indexes(drop_origianls=True)    

  indexes = self.indexes()
  others = filter(lambda c: not c in indexes, self.columns)

  categorical_df = self[indexes]    
  others_df = sparse.coo_matrix(self[others].values)

  # Destroy original as it now just takes up memory
  self.drop(self.columns, 1, inplace=True) 
  gc.collect()

  ohe_sparse = None
  for i, c in enumerate(indexes):
    col_ohe = OneHotEncoder(categorical_features=[0], dtype=dtype).\
      fit_transform(categorical_df[[c]])
    if ohe_sparse == None: ohe_sparse = col_ohe
    else: ohe_sparse = sparse.hstack((ohe_sparse, col_ohe))
    categorical_df.drop(c, axis=1, inplace=True)
    gc.collect()

  return ohe_sparse if not others else sparse.hstack((ohe_sparse, others_df))

def _df_to_indexes(self, drop_origianls=False):
  start('indexing categoricals in data frame')  
  for c in self.categoricals():
    cat = pd.Categorical.from_array(self[c])
    self['i_' + c] = pd.Series(cat.codes if hasattr(cat, 'codes') else cat.labels)
    if drop_origianls: self.drop(c, 1, inplace=True)
  stop('done indexing categoricals in data frame')  
  return self

def _df_bin(self, n_bins=100, drop_origianls=False):
  start('binning data into ' + `n_bins` + 
      ' bins. note: binning rarely helps any classifier')  
  for n in self.numericals():
    self['c_binned_' + n] = pd.cut(self[n], n_bins)
    if drop_origianls: self.drop(n, 1, inplace=True)
  stop('done binning data into ' + `n_bins` + ' bins')  
  return self

def _df_combinations(self, group_size=2, columns=[], categoricals=False, 
    numericals=False, dates=False, binaries=False):
  cols = list(columns)
  if categoricals: cols = cols + self.categoricals()
  if numericals: cols = cols + self.numericals()
  if dates: cols = cols + self.dates()
  if binaries: cols = cols + self.binaries()
  return list(itertools.combinations(cols, group_size))

def _df_remove(self, columns=[], categoricals=False, numericals=False, 
    dates=False, binaries=False, missing_threshold=0.0):  
  cols = list(columns)
  if categoricals: cols = cols + self.categoricals()
  if numericals: cols = cols + self.numericals()
  if dates: cols = cols + self.dates()
  if binaries: cols = cols + self.binaries()
  if missing_threshold > 0:
    for c in self.columns:
      nvc = self[c].isnull().value_counts()  
      if True in nvc and False in nvc and \
          nvc[True] / float(len(self)) > missing_threshold:
        cols.append(c)
  cols = set(cols)
  if len(cols) == 0: 
    raise Exception('At least one of categoricals, numericals, ' +
      'dates binaries should be set to True or columns array passed')

  debug('removing from data frame: ' + `cols`)
  self.drop(cols, 1, inplace=True)
  return self

def _df_engineer(self, name, columns=None, quiet=False):  
  '''
  name(Array|string): Can list-like of names.  ';' split list of names 
  also supported
  '''
  if type(name) is str and ';' in name: name = name.split(';')
  if type(name) is list or type(name) is tuple: 
    for n in name: self.engineer(n)
    return

  def func_to_string(c):
    func = c.func
    args = c.args
    return func + '(' + ','.join(map(lambda a: 
      func_to_string(a) if hasattr(a, 'func') else a, args)) + ')'
  
  def get_new_col_name(c):
    prefix = 'c_' if c.func == 'concat' else 'n_'    
    return prefix + func_to_string(c)

  name = name.replace(' ' , '')  
  if name in self.columns: return # already created column

  c = explain(name)[0]
  func = c.func
  args = c.args

  # Evaluate any embedded expressions in the 'name' expression
  for i, a in enumerate(args): 
    if hasattr(a, 'func'): 
      args[i] = get_new_col_name(a)
      self.engineer(func_to_string(a))

  print 'name:', name, 'func:', func, 'args:', args

  if not quiet: debug('engineering feature: ' + name)
  if len(args) == 0 and (name == 'mult' or name == 'concat'):
    combs = itertools.combinations(columns, 2) if columns \
      else self.combinations(categoricals=name=='concat', numericals='mult')    
    for c1, c2 in combs: self.engineer(func + '(' + c1 + ',' + c2 + ')', quiet=True)
  elif func == 'concat': 
    def to_obj(col):
      if not col in self: raise Exception('could not find "' + col + '" in data frame')
      return self[col] if self[col].dtype == 'object' else self[col].astype('str')
    
    if len(args) < 2 or len(args) > 3: raise Exception(name + ' only supports 2 or 3 columns')
    if len(args) == 2: 
      self['c_' + name] = to_obj(args[0]) + to_obj(args[1])
    if len(args) == 3: 
      self['c_' + name] = to_obj(args[0]) + to_obj(args[1]) + to_obj(args[2])
  elif func  == 'mult':     
    if len(args) < 2 or len(args) > 3: raise Exception(name + ' only supports 2 or 3 columns')
    if len(args) == 2: 
      self['n_' + name] = self[args[0]] * self[args[1]]
    if len(args) == 3: 
      self['n_' + name] = self[args[0]] * self[args[1]] * self[args[2]]
  elif len(args) == 1 and func == 'pow':
    cols = columns if columns else self.numericals()
    for n in cols: self.engineer('pow(' + n + ', ' + args[0] + ')', quiet=True)
  elif len(args) == 0 and func == 'lg':
    cols = columns if columns else self.numericals()
    for n in cols: self.engineer('lg(' + n + ')', quiet=True)    
  elif func == 'pow': 
    self['n_' + name] = np.power(self[args[0]], int(args[1]))
  elif func == 'lg': self['n_' + name] = np.log(self[args[0]])
  elif func.startswith('rolling_'):
    if len(args) == 1:
      cols = columns if columns else self.numericals()
      for n in cols: self.engineer(func + '(' + n + ', ' + args[0] + ')', quiet=True)
    else:      
      self['n_' + name] = getattr(pd, func)(self[args[0]], int(args[1]))
  else: raise Exception(name + ' is not supported')
  return self
  
def _df_scale(self, min_max=None):  
  start('scaling data frame')
  for c in self.numericals():
    if min_max:
      self[c] -= self[c].min()  
      self[c] /= self[c].max()
      self[c] *= (min_max[1] - min_max[0])
      self[c] += min_max[0]
    else:
      self[c] -= self[c].mean()
      self[c] /= self[c].std()
    gc.collect()
  stop('scaling data frame')
  return self

def _df_missing(self, categorical_fill='none', numerical_fill='none'):  
  start('replacing missing data categorical[' + `categorical_fill` + '] numerical[' + `numerical_fill` + ']')
  for c in self.columns: 
    fill_mode = 'none'
    if c in self.categoricals(): fill_mode = categorical_fill
    elif c in self.indexes(): fill_mode = categorical_fill
    elif c in self.numericals(): fill_mode = numerical_fill    
    if fill_mode == 'none': continue
    self[c] = self[c].fillna(_get_col_aggregate(self[c], fill_mode))
  stop('done replacing missing data')
  return self

def _get_col_aggregate(col, mode):
  '''
  col: A pandas column
  mode: One of <constant>|mode|mean|median|min|max
  '''
  if type(mode) != str: return mode
  if mode == 'mode': return col.mode().iget(0) 
  if mode == 'mean': return col.mean()
  if mode == 'median': return col.median()
  if mode == 'min': return col.min()
  if mode == 'max': return col.max()
  return mode

def _df_outliers(self, stds=3):  
  start('restraining outliers, standard deviations: ' + `stds`)
  for n in self.numericals(): 
    col = self[n]
    mean, offset = col.mean(), stds * col.std()
    min, max = mean - offset, mean + offset
    self[n] = col.clip(min, max)
  stop('done restraining outliers')
  return self

def _df_categorical_outliers(self, min_size=0.01, fill_mode='mode'):    
  threshold = float(len(self)) * min_size if type(min_size) is float else min_size
  start('binning categorical outliers, threshold: ' + `threshold`)

  tot_changed = 0
  for c in self.categoricals():     
    col = self[c]
    fill = _get_col_aggregate(col, fill_mode)
    vc = col.value_counts()
    under = vc[vc <= threshold]    
    if under.shape[0] > 0:
      tot_changed += under.sum()
      col[col.isin(under.index)] = fill
  stop('done binning categorical outliers, ' + `tot_changed` + ' cells changed')
  return self

def _df_append_right(self, df_or_s):  
  start('appending to the right.  note, this is a destructuve operation')
  if (type(df_or_s) is sparse.coo.coo_matrix):
    self_sparse = None
    for c in self.columns:
      debug('\tappending column: ' + c)
      c_coo = sparse.coo_matrix(self[[c]])
      self.drop([c], 1, inplace=True)
      gc.collect()
      if self_sparse == None: self_sparse = c_coo
      else: self_sparse = sparse.hstack((self_sparse, c_coo)) 
    self_sparse = sparse.hstack((self_sparse, df_or_s))
    stop('done appending to the right')
    return self_sparse
  elif ((type(df_or_s) is pd.sparse.frame.SparseDataFrame or 
      type(df_or_s) is pd.sparse.series.SparseSeries) and 
      not type(self) is pd.sparse.frame.SparseDataFrame):
    debug('converting data frame to a sparse frame')
    self = self.to_sparse(fill_value=0)
  if type(df_or_s) is pd.Series: self[df_or_s.name] = df_or_s.values
  else: self = pd.concat((self, df_or_s), 1)
  stop('done appending to the right')
  return self

def _df_append_bottom(self, df):  
  debug('warning: DataFrame.append_bottom always returns a new DataFrame')
  return pd.concat((self, df), 0)

def _df_shuffle(self, y):  
  start('shuffling data frame')
  new_X, new_y = utils.shuffle(self, y, random_state=sys_seed)
  start('done, shuffling data frame')
  return (pd.DataFrame(columns=self.columns, data=new_X), pd.Series(new_y))

def _df_cv(self, clf, y, n_samples=25000, n_iter=3, scoring=None):  
  _df_cv_impl_(self, clf, y, n_samples, n_iter, scoring)

def _df_cv_ohe(self, clf, y, n_samples=25000, n_iter=3, scoring=None):  
  _df_cv_impl_(self.one_hot_encode(), clf, y, n_samples, n_iter, scoring)

def _df_cv_impl_(X, clf, y, n_samples=25000, n_iter=3, scoring=None):  
  if hasattr(y, 'values'): y = y.values
  n_samples = min(n_samples, X.shape[0])
  if utils.multiclass.type_of_target(y) == 'binary': scoring = 'roc_auc'
  start('starting ' + `n_iter` + ' fold cross validation (' + 
      `n_samples` + ' samples) w/ metric: ' + `scoring`)
  cv = do_cv(clf, X, y, n_samples, n_iter=n_iter, scoring=scoring, quiet=True)
  stop('done cross validation:\n  [CV]: ' + ("{0:.3f} (+/-{1:.3f})").format(cv[0], cv[1]))  

# Data Frame Extensions  
pd.DataFrame.one_hot_encode = _df_one_hot_encode
pd.DataFrame.to_indexes = _df_to_indexes
pd.DataFrame.bin = _df_bin
pd.DataFrame.remove = _df_remove
pd.DataFrame.engineer = _df_engineer
pd.DataFrame.combinations = _df_combinations
pd.DataFrame.missing = _df_missing
pd.DataFrame.scale = _df_scale
pd.DataFrame.outliers = _df_outliers
pd.DataFrame.categorical_outliers = _df_categorical_outliers
pd.DataFrame.append_right = _df_append_right
pd.DataFrame.append_bottom = _df_append_bottom
pd.DataFrame.shuffle = _df_shuffle
pd.DataFrame.cv = _df_cv
pd.DataFrame.cv_ohe = _df_cv_ohe

pd.DataFrame.categoricals = _df_categoricals
pd.DataFrame.indexes = _df_indexes
pd.DataFrame.numericals = _df_numericals
pd.DataFrame.dates = _df_dates
pd.DataFrame.binaries = _df_binaries

# Series Extensions  
pd.Series.one_hot_encode = _s_one_hot_encode
pd.Series.bin = _s_bin

# Aliases
pd.DataFrame.ohe = _df_one_hot_encode
pd.DataFrame.toidxs = _df_to_indexes
pd.DataFrame.rm = _df_remove
pd.DataFrame.eng = _df_engineer
pd.DataFrame.nas = _df_missing
pd.DataFrame.catout = _df_categorical_outliers