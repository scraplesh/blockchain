from gevent import monkey; monkey.patch_all()  # noqa

import hashlib
import itertools
import json
import time
import typing

import bottle
import ecdsa

EMIT_PORTION = 50
CHECK_TRANSACTIONS_DELAY = 3

account = None
blockchain = []
unconfirmed_transactions = []
utxo = []
is_mining = False


@bottle.post('/create-account')
def create_account():
  global account
  if account is not None:
    bottle.abort(400, 'account is already created')

  password = (bottle.request.json or {}).get('password')
  if password is None:
    bottle.abort(400, 'Invalid password')

  global account
  account = {
      'password_hash': int(hashlib.sha1(password.encode()).hexdigest(), 16),
      'private_key': int(ecdsa.SigningKey.generate().to_string().hex(), 16)
  }

  return 'account created'


@bottle.post('/initial-emit')
def initial_emit():
  if blockchain:
    bottle.abort(400, 'Genesis block is already created')

  if account is None:
    bottle.abort(400, 'account not found')

  password = (bottle.request.json or {}).get('password')
  if not is_password_valid(account, password):
    bottle.abort(400, 'Invalid password')

  inputs = []
  outputs = [{'receiver': get_account_address(account), 'amount': EMIT_PORTION}]
  unconfirmed_transactions.append({
      'txid': get_txid(inputs, outputs),
      'inputs': inputs,
      'outputs': outputs
  })

  utxo.extend(outputs)


@bottle.post('/transfer')
def transfer():
  if account is None:
      bottle.abort(400, 'account not found')

  password = (bottle.request.json or {}).get('password')
  if not is_password_valid(account, password):
      bottle.abort(400, 'Invalid password')

  receiver = (bottle.request.json or {}).get('receiver')
  if receiver is None:
      bottle.abort(400, 'Missing receiver address')

  amount = (bottle.request.json or {}).get('amount')
  if amount is None:
      bottle.abort(400, 'Missing amount')

  current_blockchain = blockchain.copy()
  account_address = get_account_address(account.private_key)
  account_balance = get_account_balance(current_blockchain, account_address)
  if amount > account_balance:
      bottle.abort(400, 'Not enough tokens')

  outputs = TransactionOutput(receiver, amount)

  incoming_transactions = (
      transaction
      for block in current_blockchain
      for transaction in block.transactions
      if transaction.transfer.output.account_address == account_address
  )
  transaction_spends = {
      transaction_input.transaction_hash: sum(
          transaction_input.amount for transaction_input in transaction_inputs
      )
      for transaction_input, transaction_inputs in itertools.groupby(
          sorted(
              (
                  transaction_input
                  for block in current_blockchain
                  for transaction in block.transactions
                  for transaction_input in transaction.transfer.inputs or []
                  for block1 in current_blockchain
                  for transaction1 in block1.transactions
                  if transaction1.hash == transaction_input.transaction_hash and
                  transaction1.transfer.output.account_address == account_address
              ),
              key=lambda t: t.transaction_hash
          ),
          key=lambda t: t.transaction_hash
      )
  }
  available_amounts = sorted(
      (
          AvailableAmount(
              transaction.hash,
              transaction.transfer.output.amount - transaction_spends.get(transaction.hash, 0)
          )
          for transaction in incoming_transactions
          if transaction.transfer.output.amount - transaction_spends.get(transaction.hash, 0) > 0
      ),
      key=lambda available_amount: available_amount.amount
  )

  inputs = []
  checking_amount = amount
  for available_amount in available_amounts:
      if available_amount.amount >= checking_amount:
          inputs.append(TransactionInput(available_amount.transaction_hash, checking_amount))
          break

      inputs.append(
          TransactionInput(
              available_amount.transaction_hash,
              checking_amount - available_amount.amount
          )
      )
      checking_amount -= available_amount.amount

  transfer = TransactionTransfer(inputs, output)
  transaction_hash = get_txid(transfer)
  transaction = Transaction(transaction_hash, transfer)

  unconfirmed_transactions.append(transaction)


@bottle.post('/mine')
def mine():
    if not blockchain:
        bottle.abort(400, 'Cannot mine on empty blockchain')

    global is_mining
    is_mining = True
    while is_mining:
        if not unconfirmed_transactions:
            yield 'No transactions to mine. Waiting...\n'
            time.sleep(CHECK_TRANSACTIONS_DELAY)
            continue

        yield 'New transactions found. Mining...\n'

        transactions = unconfirmed_transactions.copy()
        unconfirmed_transactions.clear()

        previous_block = blockchain[-1]
        new_block = create_block(previous_block.block_hash, transactions)

        blockchain.append(new_block)

    yield 'Mining stopped'


@bottle.post('/stop-mining')
def stop_mining():
    global is_mining
    is_mining = False


def create_block(previous_block_hash, transactions):
    block_hash = hashlib.sha1(json.dumps(transactions).encode()).hexdigest()
    return Block(previous_block_hash, block_hash, transactions)


def get_account_address(account):
    return account['private_key'].get_verifying_key().to_string().hex()


def get_account_balance(blockchain, account_address):
    income = sum(
        transaction.transfer.output.amount
        for block in blockchain
        for transaction in block.transactions
        if transaction.transfer.output.account_address == account_address
    )
    waste = sum(
        transaction_input.amount
        for block in blockchain
        for transaction in block.transactions
        for transaction_input in transaction.transfer.inputs or []
        for block1 in blockchain
        for transaction1 in block1.transactions
        if transaction1.hash == transaction_input.transaction_hash and
        transaction1.transfer.output.account_address == account_address
    )

    return income - waste


def get_txid(inputs, outputs):
    return int(hashlib.sha1(json.dumps(inputs + outputs).encode()).hexdigest(), 16)


def is_password_valid(account, password):
    return (
        password is not None and
        hashlib.sha1(password.encode()).hexdigest() == account['password_hash']
    )


bottle.run(host='0.0.0.0', server='gevent')
