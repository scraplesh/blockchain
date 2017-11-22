from gevent import monkey; monkey.patch_all()  # noqa

import hashlib
import json
import time

import bottle
import ecdsa

account = None
blockchain = []
unconfirmed_transactions = []
is_mining = False


@bottle.post('/create-account')
def create_account():
  global account
  if account is not None:
    bottle.abort(400, 'Account is already created')

  password = (bottle.request.json or {}).get('password')
  if password is None:
    bottle.abort(400, 'Invalid password')

  account = {
      'password_hash': hashlib.sha1(password.encode()).hexdigest(),
      'private_key': ecdsa.SigningKey.generate()
  }

  return 'Account created'


@bottle.post('/emit')
def emit():
  if blockchain:
    bottle.abort(400, 'Genesis block is already created')

  if account is None:
    bottle.abort(400, 'Account not found')

  password = (bottle.request.json or {}).get('password')
  if not is_password_valid(account, password):
    bottle.abort(400, 'Invalid password')

  amount = (bottle.request.json or {}).get('amount')
  if amount is None:
    bottle.abort(400, 'Invalid amount')

  inputs = []
  receiver = get_address(account)
  output = get_output(receiver, amount)
  unconfirmed_transactions.append({
      'transaction_id': get_transaction_id(inputs, output),
      'inputs': inputs,
      'output': output
  })

  return f'Emitted {amount} tokens'


@bottle.post('/transfer')
def transfer():
  if account is None:
    bottle.abort(400, 'Account not found')

  password = (bottle.request.json or {}).get('password')
  if not is_password_valid(account, password):
    bottle.abort(400, 'Invalid password')

  receiver = (bottle.request.json or {}).get('receiver')
  if receiver is None:
    bottle.abort(400, 'Missing receiver address')

  amount = (bottle.request.json or {}).get('amount')
  if amount is None:
    bottle.abort(400, 'Missing amount')

  output = get_output(receiver, amount)

  address = get_address(account)
  account_utxo = sorted(
      [
          transaction
          for transaction in get_utxo(blockchain.copy())
          if transaction['receiver'] == address and transaction['output']['amount'] > amount
      ],
      key=lambda transaction: transaction['amount'],
      reversed=True
  )
  inputs = []
  inputs_sum = 0
  for transaction in account_utxo:
    if inputs_sum < amount:
      transaction_amount = transaction['output']['amount']
      if transaction_amount < amount - inputs_sum:
        inputs_sum += transaction_amount
        inputs.append({'transaction_id': transaction['transaction_id']})

  unconfirmed_transactions.append({
      'transaction_id': get_transaction_id(inputs, output),
      'inputs': inputs,
      'output': output
  })

  return f'Transfered {amount} tokens from {address} to {receiver}'


@bottle.post('/mine')
def mine():
  check_delay = int((bottle.request.json or {}).get('check_delay'))
  if check_delay is None:
    bottle.abort(400, 'Check delay not found')

  global is_mining
  is_mining = True
  while is_mining:
      if not unconfirmed_transactions:
          yield 'No transactions to mine. Waiting...\n'
          time.sleep(check_delay)
          continue

      yield 'New transactions found. Mining...\n'

      transactions = unconfirmed_transactions.copy()
      unconfirmed_transactions.clear()

      previous_block = blockchain[-1] if blockchain else None
      new_block = create_block(previous_block, transactions)

      blockchain.append(new_block)

  yield 'Mining stopped'


@bottle.post('/stop-mining')
def stop_mining():
    global is_mining
    is_mining = False


def get_utxo(blockchain):
  inputs = [
      txin['output']['transaction_id']
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


bottle.run(host='0.0.0.0', server='gevent')
