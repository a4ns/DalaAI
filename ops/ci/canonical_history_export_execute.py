#!/usr/bin/env python3
"""Private unittest execution adapter; the six authored tests remain unchanged."""
import argparse
import contextlib
import importlib.metadata
import importlib.util
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

CONTRACT=Path(__file__).with_name('canonical_history_export_contract.json')
CATEGORIES={'ASSERTION_FAILED','IMPORT_FAILED','RENDER_DOMAIN_ERROR','OTHER_ERROR'}
CODES={'TEMPORARILY_UNAVAILABLE','REPORT_LIMIT_EXCEEDED'}


def failure(error):
    seen=set();pending=[error];timeout=False;code='NONE'
    for _ in range(16):
        if not pending:break
        item=pending.pop()
        if item is None or id(item) in seen:continue
        seen.add(id(item));timeout=timeout or isinstance(item,subprocess.TimeoutExpired)
        if type(item).__name__=='DomainError' and type(item).__module__=='app.orders.models' and getattr(item,'code',None) in CODES:code=item.code
        pending.extend((getattr(item,'__cause__',None),getattr(item,'__context__',None)))
    category='ASSERTION_FAILED' if isinstance(error,AssertionError) else 'IMPORT_FAILED' if isinstance(error,ImportError) else 'RENDER_DOMAIN_ERROR' if type(error).__name__=='DomainError' else 'OTHER_ERROR'
    return {'category':category,'domain_code':code,'subprocess_timeout_observed':timeout}


class PrivateStream(io.StringIO):
    def write(self,value):
        if self.tell()+len(value)>1024*1024:raise RuntimeError('PRIVATE_OUTPUT_BOUND')
        return super().write(value)


class FixedResult(unittest.TextTestResult):
    allowed=()
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.fixed={};self.started={};self.fixture_errors=[]
    def startTest(self,test):
        super().startTest(test);self.started[test.id()]=time.monotonic()
    def record(self,test,status,error=None):
        name=test.id()
        if name not in self.allowed:
            self.fixture_errors.append(failure(error) if error else {'category':'OTHER_ERROR','domain_code':'NONE','subprocess_timeout_observed':False});return
        if name in self.fixed:raise RuntimeError('DUPLICATE_TEST_RESULT')
        duration=max(0,min(90000,round((time.monotonic()-self.started.get(name,time.monotonic()))*1000)))
        self.fixed[name]={'id':name,'status':status,'duration_ms':duration,'failure':failure(error) if error else None}
    def addSuccess(self,test):super().addSuccess(test);self.record(test,'PASS')
    def addFailure(self,test,err):super().addFailure(test,err);self.record(test,'FAIL',err[1])
    def addError(self,test,err):super().addError(test,err);self.record(test,'ERROR',err[1])
    def addSkip(self,test,reason):super().addSkip(test,reason);self.record(test,'SKIP')
    def addExpectedFailure(self,test,err):super().addExpectedFailure(test,err);self.record(test,'EXPECTED_FAILURE',err[1])
    def addUnexpectedSuccess(self,test):super().addUnexpectedSuccess(test);self.record(test,'UNEXPECTED_SUCCESS')


def flatten(suite):
    for test in suite:
        if isinstance(test,unittest.TestSuite):yield from flatten(test)
        else:yield test


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);args=parser.parse_args();source=args.source.resolve()
    c=json.loads(CONTRACT.read_text());summary={'schema_version':1,'status':'BLOCKED','cases':[],'fixture_errors':[],'tests_run':0};code=2
    private=PrivateStream()
    try:
        if platform.python_version()!=c['python'] or sys.prefix==sys.base_prefix:raise RuntimeError('EXACT_ISOLATED_PYTHON_REQUIRED')
        versions={name:importlib.metadata.version(name) for name in c['export_packages']}
        if versions!=c['export_packages']:raise RuntimeError('LOCKED_EXPORT_PACKAGES_REQUIRED')
        optional={name:importlib.util.find_spec(name) is not None for name in ('lxml','numpy')}
        if any(optional.values()):raise RuntimeError('UNLOCKED_OPTIONAL_PACKAGE_PRESENT')
        summary.update(python=platform.python_version(),packages=versions,optional_packages=optional)
        sys.path.insert(0,str(source/'backend'));sys.dont_write_bytecode=True
        with contextlib.redirect_stdout(private),contextlib.redirect_stderr(private):
            suite=unittest.defaultTestLoader.discover(str(source/'backend/tests'),pattern='test_c_day_canonical_history_exports.py',top_level_dir=str(source/'backend/tests'))
            names=[test.id() for test in flatten(suite)]
            if len(names)!=6 or sorted(names)!=sorted(c['cases']):raise RuntimeError('EXACT_SIX_TESTS_REQUIRED')
            FixedResult.allowed=tuple(c['cases'])
            result=unittest.TextTestRunner(stream=private,verbosity=2,resultclass=FixedResult,failfast=False).run(suite)
        summary['tests_run']=result.testsRun
        summary['cases']=[result.fixed.get(name,{'id':name,'status':'NOT_RUN','duration_ms':0,'failure':None}) for name in c['cases']]
        summary['fixture_errors']=result.fixture_errors[:6]
        passed=result.wasSuccessful() and result.testsRun==6 and not result.fixture_errors and all(row['status']=='PASS' for row in summary['cases'])
        summary['status']='PASS' if passed else 'FAIL';code=0 if passed else 1
    except Exception as error:
        fixed=str(error)
        summary['reason_code']=fixed if fixed in {'EXACT_ISOLATED_PYTHON_REQUIRED','LOCKED_EXPORT_PACKAGES_REQUIRED','UNLOCKED_OPTIONAL_PACKAGE_PRESENT','EXACT_SIX_TESTS_REQUIRED','PRIVATE_OUTPUT_BOUND','DUPLICATE_TEST_RESULT'} else 'EXECUTION_SETUP_OR_RESULT_ERROR'
        summary['setup_failure']=failure(error)
    finally:private.close()
    print(json.dumps(summary));return code


if __name__=='__main__':raise SystemExit(main())
