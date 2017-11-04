#!/usr/bin/env python3
import pickle
import base64
import os

import paho.mqtt.client as mqtt

from cryptography.fernet import Fernet

from pycrdt.crdt.crdt import CRDTDoc


key = b"7tLEmPE51jXJRwNUIu5zQOOsoMwjlfgydyVeI2n8guw="
f = Fernet(key)

doc = CRDTDoc()
string = "Welcome to PyCRDT - a real CRDT implementation!\n\nThis pad text is synchronized as you type!\n"
for i, s in enumerate(string):
    doc.insert(i, s)

doc.debug()

enc = f.encrypt(pickle.dumps(doc))

client = mqtt.Client()
client.connect("iot.eclipse.org", 1883, 60)
client.publish("test/pad/demo", "i ".encode() + enc, retain=True)

print("Key:", key)
