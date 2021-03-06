#----------------------------------------------------------------------
# Copyright 2012, 2013 Arndt Droullier, Nive GmbH. All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#----------------------------------------------------------------------
"""
Data Pool Sqlite Module
----------------------
*Requires python-sqlite*
"""

import threading
import sqlite3
from time import time

from nive.utils.utils import STACKF

from nive.utils.dataPool2.base import Base, Entry
from nive.utils.dataPool2.base import NotFound
from nive.utils.dataPool2.connection import Connection, ConnectionThreadLocal, ConnectionRequest

from nive.utils.dataPool2.files import FileManager, FileEntry
from nive.utils.dataPool2.dbManager import Sqlite3Manager

from nive.definitions import OperationalError



class Sqlite3Connection(Connection):
    """
    Sqlite connection handling class

    config parameter in dictionary:
    db = database path
    
    user = unused - database user
    password = unused - password user
    host = unused - host server
    port = unused - port server

    timeout is set to 3.
    """

    def __init__(self, config = None, connectNow = True):
        self.db = None
        self.configuration = config
        
        self.placeholder = u"?"
        self.check_same_thread = False
        if connectNow:
            self.connect()
        

    def ping(self):
        """ ping database server """
        return True


    def connect(self):
        """ Close and connect to server """
        #t = time()
        conf = self.configuration
        if not conf.dbName:
            raise OperationalError, "Connection failed. Database name is empty." 
        db = sqlite3.connect(conf.dbName, check_same_thread=self.check_same_thread)
        if not db:
            raise OperationalError, "Cannot connect to database '%s'" % (conf.dbName)
        c = db.cursor()
        c.execute("PRAGMA journal_mode = TRUNCATE")
        #c.execute("PRAGMA secure_delete = 0")
        #c.execute("PRAGMA temp_store = MEMORY")
        c.execute("PRAGMA synchronous = OFF")
        c.close()
        self._set(db)
        #print "connect:", time() - t
        return db


    def IsConnected(self):
        """ Check if database is connected """
        try:
            db = self._get()
            return db.cursor()!=None
        except:
            return False
    

    def GetDBManager(self):
        """ returns the database manager obj """
        aDB = Sqlite3Manager()
        aDB.SetDB(self.PrivateConnection())
        return aDB


    def FmtParam(self, param):
        """ format a parameter for sql queries like literal for  db"""
        if isinstance(param, (int, long, float)):
            return unicode(param)
        d = unicode(param)
        if d.find(u'"')!=-1:
            d = d.replace(u'"',u'\\"')
        return u'"%s"'%d


    def PrivateConnection(self):
        """ This function will return a new and raw connection. It is up to the caller to close this connection. """
        conf = self.configuration
        if not conf.dbName:
            raise OperationalError, "Connection failed. Database name is empty." 
        db = sqlite3.connect(conf.dbName, check_same_thread=self.check_same_thread)
        return db



class Sqlite3ConnThreadLocal(Sqlite3Connection, ConnectionThreadLocal):
    """
    Caches database connections as thread local values.
    """

    def __init__(self, config = None, connectNow = True):
        self.local = threading.local()
        Sqlite3Connection.__init__(self, config, False)
        self.check_same_thread = True
        if connectNow:
            self.connect()

        
class Sqlite3ConnRequest(Sqlite3Connection, ConnectionRequest):
    """
    Caches database connections as request values. Uses thread local stack as fallback (e.g testing).
    """

    def __init__(self, config = None, connectNow = True):
        self.local = threading.local()
        Sqlite3Connection.__init__(self, config, False)
        self.check_same_thread = True
        if connectNow:
            self.connect()
    



class Sqlite3(FileManager, Base):
    """
    Data Pool Sqlite3 implementation
    """
    _OperationalError = sqlite3.OperationalError
    _DefaultConnection = Sqlite3ConnRequest
    _EmptyValues = []


    def GetContainedIDs(self, base=0, sort=u"title", parameter=u""):
        """
        select list of all entries
        id needs to be first field, pool_unitref second
        """
        def _SelectIDs(base, ids, sql, cursor):
            cursor.execute(sql%(base))
            entries = cursor.fetchall()
            for e in entries:
                ids.append(e[0])
                ids = _SelectIDs(e[0], ids, sql, cursor)
            return ids
        parameter = u"where pool_unitref=%d " + parameter
        sql = u"""select id from %s %s order by %s""" % (self.MetaTable, parameter, sort)
        cursor = self.connection.cursor()
        ids = _SelectIDs(base, [], sql, cursor)
        cursor.close()
        return ids


    def GetTree(self, flds=[u"id"], sort=u"title", base=0, parameter=u""):
        """
        select list of all entries
        id needs to be first field if flds
        """
        def _Select(base, tree, flds, sql, cursor):
            cursor.execute(sql%(base))
            entries = cursor.fetchall()
            for e in entries:
                data = self.ConvertRecToDict(e, flds)
                data.update({"id": e[0], "items": []})
                tree["items"].append(data)
                data = _Select(e[0], data, flds, sql, cursor)
            return tree

        if parameter != u"":
            parameter = u"and " + parameter
        parameter = u"where pool_unitref=%d " + parameter
        sql = u"""select %s from %s %s order by %s""" % (ConvertListToStr(flds), self.MetaTable, parameter, sort)
        cursor = self.connection.cursor()
        tree = {"id":base, "items":[]}
        tree = _Select(base, tree, flds, sql, cursor)
        cursor.close()
        return tree


    def _GetInsertIDValue(self, cursor):
        cursor.execute(u"SELECT last_insert_rowid()")
        return cursor.fetchone()[0]

               
    def _CreateNewID(self, table = u"", dataTbl = None):
        #
        aC = self.connection.cursor()
        if table == "":
            table = self.MetaTable
        if table == self.MetaTable:
            if not dataTbl:
                raise "Missing data table", "Entry not created"

            # sql insert empty rec in data table
            if self._debug:
                STACKF(0,u"INSERT INTO %s (id) VALUES(null)" % (dataTbl)+"\r\n",self._debug, self._log,name=self.name)
            aC.execute(u"INSERT INTO %s (id) VALUES(null)" % (dataTbl))
            # sql get id of created rec
            if self._debug:
                STACKF(0,u"SELECT last_insert_rowid()\r\n",0, self._log,name=self.name)
            aC.execute(u"SELECT last_insert_rowid()")
            dataref = aC.fetchone()[0]
            # sql insert empty rec in meta table
            if self._debug:
                STACKF(0,u"INSERT INTO %s (pool_datatbl, pool_dataref) VALUES ('%s', %s)"% (self.MetaTable, dataTbl, dataref),0, self._log,name=self.name)
            aC.execute(u"INSERT INTO %s (pool_datatbl, pool_dataref) VALUES ('%s', %s)"% (self.MetaTable, dataTbl, dataref))
            if self._debug:
                STACKF(0,u"SELECT last_insert_rowid()\r\n",0, self._log,name=self.name)
            aC.execute(u"SELECT last_insert_rowid()")
            aID = aC.fetchone()[0]
            aC.close()
            return aID, dataref

        # sql insert empty rec in meta table
        if self._debug:
            STACKF(0,u"INSERT INTO %s (id) VALUES(null)" % (table)+"\r\n",self._debug, self._log,name=self.name)
        aC.execute(u"INSERT INTO %s (id) VALUES(null)" % (table))
        # sql get id of created rec
        if self._debug:
            STACKF(0,u"SELECT last_insert_rowid()\r\n",0, self._log,name=self.name)
        aC.execute(u"SELECT last_insert_rowid()")
        aID = aC.fetchone()[0]
        aC.close()
        return aID, 0


    def _CreateFixID(self, id, dataTbl):
        if self.IsIDUsed(id):
            raise TypeError, "ID already in use"
        aC = self.connection.cursor()
        ph = self.placeholder
        if not dataTbl:
            raise TypeError, "Missing data table."

        # sql insert empty rec in data table
        if self._debug:
            STACKF(0,u"INSERT INTO %s (id) VALUES(null)" % (dataTbl)+"\r\n",self._debug, self._log,name=self.name)
        aC.execute(u"INSERT INTO %s (id) VALUES(null)" % (dataTbl))
        # sql get id of created rec
        if self._debug:
            STACKF(0,u"SELECT last_insert_rowid()\r\n",0, self._log,name=self.name)
        aC.execute(u"SELECT last_insert_rowid()")
        dataref = aC.fetchone()[0]
        # sql insert empty rec in meta table
        if self._debug:
            STACKF(0,u"INSERT INTO %s (id, pool_datatbl, pool_dataref) VALUES (%d, '%s', %s)"% (self.MetaTable, id, dataTbl, dataref),0, self._log,name=self.name)
        aC.execute(u"INSERT INTO %s (id, pool_datatbl, pool_dataref) VALUES (%d, '%s', %s)"% (self.MetaTable, id, dataTbl, dataref))
        if self._debug:
            STACKF(0,u"SELECT last_insert_rowid()\r\n",0, self._log,name=self.name)
        aC.execute(u"SELECT last_insert_rowid()")
        aID = aC.fetchone()[0]
        aC.close()
        return id, dataref

    # types/classes -------------------------------------------------------------------

    def _FmtListForQuery(self, values):
        FmtParam = self.connection.FmtParam
        return u",".join([FmtParam(v) for v in values])

    def _GetPoolEntry(self, id, **kw):
        try:
            return Sqlite3Entry(self, id, **kw)
        except NotFound:
            return None



class Sqlite3Entry(FileEntry, Entry):
    """
    Data Pool Entry Sqlite3 implementation
    """


