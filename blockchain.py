import asyncio
import hashlib
import json

import ecdsa
from aiohttp import web

account = None
blockchain = []
unconfirmed_transactions = []
is_mining = False

routes = web.RouteTableDef()


@routes.post('/create-account')
async def create_account(request):
  global account
  if account is not None:
    raise web.HTTPBadRequest('Account is already created')

  body = await request.json()
  if 'password' not in body:
    raise web.HTTPBadRequest('Invalid password')

  password = body['password']
  account = {
      'password_hash': hashlib.sha1(password.encode()).hexdigest(),
      'private_key': ecdsa.SigningKey.generate()
  }

  return web.Response(text='Account created')


@routes.post('/emit')
async def emit(request):
  if blockchain:
    raise web.HTTPBadRequest('Genesis block is already created')

  if account is None:
    raise web.HTTPBadRequest('Account not found')

  body = await request.json()
  if 'password' not in body or not is_password_valid(account, body['password']):
    raise web.HTTPBadRequest('Invalid password')

  if 'amount' not in body:
    raise web.HTTPBadRequest('Invalid amount')
  amount = body['amount']

  inputs = []
  receiver = get_address(account)
  output = get_output(receiver, amount)
  unconfirmed_transactions.append({
      'transaction_id': get_transaction_id(inputs, output),
      'inputs': inputs,
      'output': output
  })

  return web.Response(text=f'Emitted {amount} tokens')


@routes.post('/transfer')
async def transfer(request):
  if account is None:
    raise web.HTTPBadRequest('Account not found')

  body = await request.json()

  if 'password' not in body or not is_password_valid(account, body['password']):
    raise web.HTTPBadRequest('Invalid password')

  if 'receiver' not in body:
    raise web.HTTPBadRequest('Missing receiver address')
  receiver = body['receiver']

  if 'amount' not in body:
    raise web.HTTPBadRequest('Missing amount')
  amount = body['amount']

  output = get_output(receiver, amount)

  address = get_address(account)
  account_utxo = sorted(
      [
          transaction
          for transaction in get_utxo(blockchain.copy())
          if transaction['output']['receiver'] == address and
          transaction['output']['amount'] > amount
      ],
      key=lambda transaction: transaction['output']['amount'],
      reverse=True
  )
  balance = sum(transaction['output']['amount'] for transaction in account_utxo)
  if balance < amount:
    raise web.HTTPBadRequest('Not enough tokens')

  inputs = []
  remaining_amount = amount
  for transaction in account_utxo:
    if remaining_amount > 0:
      inputs.append({'transaction_id': transaction['transaction_id']})
      remaining_amount -= transaction['output']['amount']

  unconfirmed_transactions.append({
      'transaction_id': get_transaction_id(inputs, output),
      'inputs': inputs,
      'output': output
  })

  return web.Response(text=f'Transfered {amount} tokens from {address} to {receiver}')


@routes.post('/mine')
async def mine(request):
  body = await request.json()
  check_delay = int(body['check_delay'])

  global is_mining
  is_mining = True

  resp = web.StreamResponse(reason='OK', headers={'Content-Type': 'text/html'})
  await resp.prepare(request)

  while is_mining:
      if not unconfirmed_transactions:
          resp.write(b'No transactions to mine. Waiting...\n')
          await resp.drain()
          await asyncio.sleep(check_delay)
          continue

      resp.write(b'New transactions found. Mining...\n')
      await resp.drain()

      transactions = unconfirmed_transactions.copy()
      unconfirmed_transactions.clear()

      previous_block = blockchain[-1] if blockchain else None
      new_block = create_block(previous_block, transactions)

      blockchain.append(new_block)

  return resp


@routes.post('/stop-mining')
async def stop_mining(request):
    global is_mining
    is_mining = False
    return web.Response(text="Mining stopped")


@routes.get('/blocks')
async def get_blocks(request):
  return web.json_response(blockchain)


def get_utxo(blockchain):
  inputs = [
      txin['transaction_id']
      for block in blockchain
      for transaction in block['transactions']
      for txin in transaction['inputs']
  ]
  return [
      transaction
      for block in blockchain
      for transaction in block['transactions']
      if transaction['transaction_id'] not in inputs
  ]


def get_output(address, amount):
  return {'receiver': address, 'amount': amount}


def create_block(previous_block, transactions):
    return {
        'previous_block_id': None if previous_block is None else previous_block['block_id'],
        'block_id': hashlib.sha1(json.dumps(transactions).encode()).hexdigest(),
        'transactions': transactions
    }


def get_address(account):
    return account['private_key'].get_verifying_key().to_string().hex()


def get_transaction_id(inputs, output):
    return hashlib.sha1(json.dumps(inputs + [output]).encode()).hexdigest()


def is_password_valid(account, password):
    return (
        password is not None and
        hashlib.sha1(password.encode()).hexdigest() == account['password_hash']
    )


app = web.Application()
app.router.add_routes(routes)

web.run_app(app, host='0.0.0.0', port=8080)
