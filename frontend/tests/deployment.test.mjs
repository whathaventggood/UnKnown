import {test} from 'node:test'
import assert from 'node:assert/strict'
import {redirectsFor} from '../../scripts/netlify-proxy.mjs'
test('same-origin Netlify API proxy precedes SPA fallback',()=>{
 assert.equal(redirectsFor('https://api.example.org'),'/api/* https://api.example.org/api/:splat 200\n/* /index.html 200\n')
 assert.equal(redirectsFor(), '/* /index.html 200\n')
})
test('proxy origin cannot inject redirects, credentials or insecure protocols',()=>{
 for(const value of ['http://api.example.org','https://user:key@api.example.org','https://api.example.org/path','https://api.example.org?key=secret','https://api.example.org\n/* https://evil.example 200','file:///tmp/local'])assert.throws(()=>redirectsFor(value))
})
