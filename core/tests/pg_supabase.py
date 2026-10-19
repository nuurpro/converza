"""Test-only PostgREST-shaped adapter backed by real isolated PostgreSQL transactions."""
from __future__ import annotations
import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor

JSON_COLUMNS={'metadata','onboarding_answers','voice_rules','negative_constraints','atoms','delivery_receipt','receipt','payload','source_snapshot','result'}


def json_default(value):
    if isinstance(value,(date,datetime)): return value.isoformat()
    if isinstance(value,Decimal): return float(value)
    if isinstance(value,UUID): return str(value)
    raise TypeError(type(value).__name__)


def normalize(value): return json.loads(json.dumps(value,default=json_default))


class PgSupabase:
    def __init__(self,dsn):
        self.dsn=dsn
        with self.connect() as conn:
            if not conn.info.dbname.startswith('test_converza'):
                raise RuntimeError('QA adapter requires disposable test_converza database')
    def connect(self): return psycopg2.connect(self.dsn)
    def table(self,name): return PgQuery(self,name)
    def rpc(self,name,params): return PgRPC(self,name,params)


class PgQuery:
    def __init__(self,client,table):
        self.client=client; self.table_name=table; self.filters=[]; self.sort=[]; self.columns='*'; self.mode='select'; self.values=None; self.maximum=None; self.offset=0; self.one=False; self.count_requested=False
    def select(self,columns='*',**kwargs): self.columns=columns; self.count_requested=kwargs.get('count')=='exact'; return self
    def eq(self,key,value): self.filters.append((key,'=',value)); return self
    def neq(self,key,value): self.filters.append((key,'<>',value)); return self
    def gt(self,key,value): self.filters.append((key,'>',value)); return self
    def gte(self,key,value): self.filters.append((key,'>=',value)); return self
    def lt(self,key,value): self.filters.append((key,'<',value)); return self
    def lte(self,key,value): self.filters.append((key,'<=',value)); return self
    def is_(self,key,value): self.filters.append((key,'IS',None if value=='null' else value)); return self
    def order(self,key,desc=False,**kwargs): self.sort.append((key,desc)); return self
    def limit(self,n): self.maximum=n; return self
    def range(self,start,end): self.offset=start; self.maximum=end-start+1; return self
    def single(self): self.one=True; return self
    def maybe_single(self): self.one=True; return self
    def insert(self,values): self.mode='insert'; self.values=values; return self
    def update(self,values): self.mode='update'; self.values=values; return self
    def delete(self): self.mode='delete'; return self
    def _adapt(self,key,value): return Json(value) if isinstance(value,dict) or (key in JSON_COLUMNS and value is not None) else value
    def execute(self):
        args=[]; target=sql.Identifier(self.table_name)
        cols=sql.SQL('*') if self.columns=='*' else sql.SQL(',').join(sql.Identifier(c.strip()) for c in self.columns.split(','))
        where=[]
        for key,op,value in self.filters:
            if op=='IS': where.append(sql.SQL('{} IS NULL').format(sql.Identifier(key)))
            else: where.append(sql.SQL('{} {} %s').format(sql.Identifier(key),sql.SQL(op))); args.append(value)
        condition=sql.SQL(' WHERE ')+sql.SQL(' AND ').join(where) if where else sql.SQL('')
        if self.mode=='select': query=sql.SQL('SELECT {} FROM {}').format(cols,target)+condition
        elif self.mode=='insert':
            values=self.values if isinstance(self.values,list) else [self.values]; keys=list(values[0]); args=[]
            groups=[]
            for value in values:
                groups.append(sql.SQL('(')+sql.SQL(',').join(sql.Placeholder() for _ in keys)+sql.SQL(')'))
                args.extend(self._adapt(key,value.get(key)) for key in keys)
            query=sql.SQL('INSERT INTO {} ({}) VALUES {} RETURNING *').format(target,sql.SQL(',').join(map(sql.Identifier,keys)),sql.SQL(',').join(groups))
        elif self.mode=='update':
            keys=list(self.values)
            if not keys: raise ValueError('Empty update')
            query=sql.SQL('UPDATE {} SET {}').format(target,sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in keys))+condition+sql.SQL(' RETURNING *')
            args=[self._adapt(k,self.values[k]) for k in keys]+args
        else: query=sql.SQL('DELETE FROM {}').format(target)+condition+sql.SQL(' RETURNING *')
        if self.mode=='select':
            if self.sort: query+=sql.SQL(' ORDER BY ')+sql.SQL(',').join(sql.SQL('{} {}').format(sql.Identifier(k),sql.SQL('DESC' if desc else 'ASC')) for k,desc in self.sort)
            if self.maximum is not None: query+=sql.SQL(' LIMIT %s'); args.append(self.maximum)
            if self.offset: query+=sql.SQL(' OFFSET %s'); args.append(self.offset)
        with self.client.connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query,args); rows=normalize(cursor.fetchall())
        if self.one: return SimpleNamespace(data=rows[0] if rows else None,count=len(rows))
        return SimpleNamespace(data=rows,count=len(rows))


class PgRPC:
    def __init__(self,client,name,params): self.client,self.name,self.params=client,name,params
    def execute(self):
        arguments=sql.SQL(',').join(sql.SQL('{} => %s').format(sql.Identifier(key)) for key in self.params)
        query=sql.SQL('SELECT * FROM {}({})').format(sql.Identifier(self.name),arguments)
        values=[Json(v) if isinstance(v,(dict,list)) else v for v in self.params.values()]
        with self.client.connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query,values); rows=normalize(cursor.fetchall()); scalar=len(cursor.description)==1 and cursor.description[0].name==self.name
        return SimpleNamespace(data=(rows[0][self.name] if rows else None) if scalar else rows)
