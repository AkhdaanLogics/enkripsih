const http=require('http'),fs=require('fs'),path=require('path');
const root=path.resolve('frontend');
http.createServer((req,res)=>{
  let p=decodeURIComponent(req.url.split('?')[0]);
  if(p.startsWith('/static/'))p=p.replace(/^\/static/,'');
  if(p==='/')p='/index.html';
  const f=path.join(root,p);
  fs.readFile(f,(e,d)=>{
    if(e){res.writeHead(404);return res.end('nf');}
    const ct=p.endsWith('.css')?'text/css':p.endsWith('.js')?'application/javascript':p.endsWith('.png')?'image/png':p.endsWith('.svg')?'image/svg+xml':'text/html';
    res.setHeader('Content-Type',ct);res.end(d);
  });
}).listen(8331,'127.0.0.1',()=>console.log('up 8331'));
